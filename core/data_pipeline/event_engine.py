"""
AUTOBOT Data Pipeline - Event Engine
Orchestrates event-driven decision making from WebSocket data

UPDATE v2.1 - Debug Logs Eklendi
- Detaylı orkestrasyon logları
- Her adım için debug trace
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from collections import defaultdict

from core.data_pipeline.websocket_collector import WebSocketCollector, MarketData, StreamType, LatencyMetrics
from core.data_pipeline.data_validator import DataValidator
from core.feature_engine.indicators import IndicatorCalculator
from core.feature_engine.regime_detector import RegimeDetector
from core.decision.rule_engine import RuleEngine
from core.decision.bias_generator import BiasAggregator
from core.risk.pre_trade_veto import PreTradeVetoChain, VetoConfig
from core.risk.position_sizer import position_sizer
from core.execution.order_manager import OrderManager
from core.execution.exit_manager import exit_manager, ExitSignal
from core.state.state_persistence import state_manager
from core.state import SystemState, SystemStatus, MarketRegime, TradeSignal, Position
from config.settings import settings
from core.notification.telegram_manager import notification_manager, NotificationPriority
from strategies.trading_rules import register_all_rules

logger = logging.getLogger("autobot.data.event_engine")


class TradingDecisionEngine:
    """
    Event-driven decision engine that processes market data
    and generates trading signals in real-time.
    """

    def __init__(self):
        # Data pipeline components
        self.ws_collector = WebSocketCollector()
        self.data_validator = DataValidator()

        # Feature calculation
        self.indicator_calculator = IndicatorCalculator()
        self.regime_detector = RegimeDetector()

        # Decision making
        self.rule_engine = RuleEngine()
        self.bias_aggregator = BiasAggregator(activation_threshold=settings.ACTIVATION_THRESHOLD)

        # Risk management
        veto_config = VetoConfig(
            max_position_size_usdt=settings.MAX_POSITION_SIZE_USDT,
            max_positions=settings.MAX_POSITIONS,
            correlation_threshold=settings.CORRELATION_THRESHOLD,
            max_correlation_exposure_pct=settings.MAX_CORRELATION_EXPOSURE_PCT,
            max_drawdown_pct=settings.MAX_DRAWDOWN_PCT,
            daily_loss_limit_pct=settings.DAILY_LOSS_LIMIT_PCT
        )
        self.veto_chain = PreTradeVetoChain(veto_config)

        # Execution
        self.order_manager = OrderManager(dry_run=settings.is_dry_run)

        # System state
        self._state: Optional[SystemState] = None

        # Feature cache (per symbol)
        self._feature_cache: Dict[str, Dict] = defaultdict(dict)

        # OHLCV data buffers (for indicator calculation)
        self._ohlcv_buffers: Dict[str, list] = defaultdict(list)

        # Decision throttling (avoid excessive decisions)
        self._last_decision_time: Dict[str, datetime] = {}
        self._min_decision_interval_seconds = 1  # Max one decision per second per symbol

        # Register event handlers
        self._register_event_handlers()

        # Register all trading rules
        register_all_rules(self.rule_engine)

        logger.info("=" * 60)
        logger.info("[ENGINE] TradingDecisionEngine initialized")
        logger.info(f"[ENGINE] Environment: {settings.ENVIRONMENT}")
        logger.info(f"[ENGINE] Dry Run: {settings.is_dry_run}")
        logger.info(f"[ENGINE] Max Positions: {settings.MAX_POSITIONS}")
        logger.info(f"[ENGINE] Activation Threshold: {settings.ACTIVATION_THRESHOLD}")
        logger.info("=" * 60)

    def _register_event_handlers(self):
        """Register callbacks for WebSocket events"""

        # Kline close events trigger decisions
        self.ws_collector.on_kline(self._on_kline_event)

        # Error handling
        self.ws_collector.on_error(self._on_error_event)

    async def start(self, symbols: list):
        """Start the event-driven trading engine"""

        logger.info("=" * 60)
        logger.info(f"[ENGINE] Starting trading engine for {len(symbols)} symbols")
        logger.info(f"[ENGINE] Symbols: {symbols[:10]}..." if len(symbols) > 10 else f"[ENGINE] Symbols: {symbols}")
        logger.info("=" * 60)

        # Load system state
        self._state = state_manager.load_state()
        if not self._state:
            self._state = SystemState(
                status=SystemStatus.RUNNING,
                equity=10000.0,
                peak_equity=10000.0
            )
            logger.info("[ENGINE] Created new system state")
        else:
            logger.info(f"[ENGINE] Loaded state: {len(self._state.open_positions)} open positions")

        # Subscribe to data streams
        self.ws_collector.subscribe_klines(symbols, interval="1m")
        self.ws_collector.subscribe_book_ticker(symbols)

        # Start WebSocket and event loop
        await self.ws_collector.start()

    async def _on_kline_event(self, data: MarketData):
        """Handle kline event (event-driven trigger)"""

        # Validate data first
        is_valid, reason = self.data_validator.validate(data)
        if not is_valid:
            logger.debug(f"[DATA] {data.symbol}: Rejected - {reason}")
            return

        # Update OHLCV buffer
        buffer_size_before = len(self._ohlcv_buffers.get(data.symbol, []))
        self._update_ohlcv_buffer(data.symbol, data)
        buffer_size_after = len(self._ohlcv_buffers[data.symbol])

        # Debug: Buffer güncellemesi
        if data.symbol in self._ohlcv_buffers and buffer_size_after != buffer_size_before:
            logger.debug(
                f"[DATA] {data.symbol}: Buffer updated ({buffer_size_after} bars) | "
                f"O={data.open:.2f} H={data.high:.2f} L={data.low:.2f} C={data.close:.2f} "
                f"V={data.volume:.2f} Closed={data.is_kline_closed}"
            )

        # Only make decisions on kline close
        if data.is_kline_closed:
            await self._on_kline_close(data)

    async def _on_kline_close(self, data: MarketData):
        """Handle kline close event - DECISION TRIGGER"""

        symbol = data.symbol
        now = datetime.now(timezone.utc)

        # Check throttling
        last_time = self._last_decision_time.get(symbol)

        if last_time:
            elapsed = (now - last_time).total_seconds()
            if elapsed < self._min_decision_interval_seconds:
                logger.debug(f"[THROTTLE] {symbol}: Skipped ({elapsed:.2f}s < {self._min_decision_interval_seconds}s)")
                return

        self._last_decision_time[symbol] = now

        # Open position check
        has_position = symbol in self._state.open_positions

        logger.info("=" * 80)
        logger.info(f"[KLINE CLOSE] {symbol} @ {data.close:.2f} | Has Position: {has_position}")
        logger.info("=" * 80)

        # Step 1: Calculate features
        logger.debug(f"[STEP 1] {symbol}: Calculating features...")
        features = await self._calculate_features(symbol)

        if not features:
            logger.warning(f"[STEP 1] {symbol}: No features calculated (insufficient data)")
            return

        # Add timestamp for exit manager
        features["timestamp"] = int(data.timestamp.timestamp() * 1000)

        # Debug: Feature özeti
        logger.debug(
            f"[FEATURES] {symbol}: "
            f"RSI={features.get('rsi', 0):.1f} "
            f"ADX={features.get('adx', 0):.1f} "
            f"EMA20={features.get('ema_20', 0):.2f} "
            f"EMA50={features.get('ema_50', 0):.2f} "
            f"ATR={features.get('atr', 0):.4f} "
            f"high_20={features.get('high_20', 0):.2f} "
            f"low_20={features.get('low_20', 0):.2f}"
        )

        # Step 2: Detect regime
        logger.debug(f"[STEP 2] {symbol}: Detecting regime...")
        current_regime = self.regime_detector.detect(features)
        volatility_regime = self.regime_detector.detect_volatility(features)

        logger.info(f"[REGIME] {symbol}: {current_regime.value} | Volatility: {volatility_regime.value}")

        # Update system state (symbol bazlı regime)
        old_regime = self._state.get_symbol_regime(symbol)
        self._state.update_symbol_regime(symbol, current_regime)
        self._state.current_regime = current_regime  # Legacy global regime
        self._state.last_update = now

        # Update exit manager with symbol regime
        exit_manager.update_symbol_regime(symbol, current_regime)

        if old_regime != current_regime and old_regime != MarketRegime.UNKNOWN:
            logger.warning(f"[REGIME CHANGE] {symbol}: {old_regime.value} → {current_regime.value}")

        # Step 3: Generate signal from Decision Engine
        logger.debug(f"[STEP 3] {symbol}: Evaluating trading rules...")
        signal = self.rule_engine.evaluate(
            symbol=symbol,
            current_regime=current_regime,
            features=features,
            strategy_name="default"
        )

        logger.info(
            f"[SIGNAL] {symbol}: {signal.action} | "
            f"Bias: {signal.bias_score:+.3f} | "
            f"Confidence: {signal.confidence:.2f} | "
            f"Active Rules: {signal.metadata.get('active_rules', 0)}"
        )

        # Step 4: Apply Risk Veto Chain
        if signal.action in ["PROPOSE_LONG", "PROPOSE_SHORT"]:
            logger.debug(f"[STEP 4] {symbol}: Running veto chain...")

            # Calculate position size (simplified - would use proper sizing logic)
            proposed_quantity = None  # Let position_sizer calculate it

            veto_result = self.veto_chain.evaluate(
                signal=signal,
                state=self._state,
                proposed_quantity=proposed_quantity,
                proposed_price=data.close
            )

            logger.debug(
                f"[VETO] {symbol}: {veto_result.veto_stage if not veto_result.approved else 'PASSED'} | "
                f"Approved: {veto_result.approved}"
            )

            if veto_result.approved:
                # Step 5: Execute approved signal
                logger.debug(f"[STEP 5] {symbol}: Executing signal...")
                await self._execute_signal(signal, data.close, 0.0)
            else:
                logger.warning(f"[VETO REJECTED] {symbol}: {veto_result.veto_reason} at {veto_result.veto_stage}")

                notification_manager.send_warning(
                    title="Trade Vetoed",
                    message=veto_result.veto_reason,
                    symbol=symbol,
                    stage=veto_result.veto_stage
                )
        elif signal.action == "CLOSE":
            # Close existing position
            logger.info(f"[SIGNAL] {symbol}: CLOSE action received")
            await self._close_position(symbol)

        # ============================================================
        # EXIT KONTROLÜ
        # ============================================================
        if symbol in self._state.open_positions:
            logger.debug(f"[STEP EXIT] {symbol}: Running exit checks...")
            await self._check_exits(symbol, data, features)
        else:
            logger.debug(f"[STEP EXIT] {symbol}: No open position, skip exit check")

    async def _calculate_features(self, symbol: str) -> Optional[Dict]:
        """Calculate technical features for a symbol"""

        buffer = self._ohlcv_buffers.get(symbol)
        if not buffer or len(buffer) < 50:
            logger.debug(f"[FEATURES] {symbol}: Insufficient buffer ({len(buffer) if buffer else 0} < 50)")
            return None

        # Convert buffer to pandas DataFrame
        try:
            import pandas as pd
            import numpy as np

            df_data = {
                "open": [k["open"] for k in buffer],
                "high": [k["high"] for k in buffer],
                "low": [k["low"] for k in buffer],
                "close": [k["close"] for k in buffer],
                "volume": [k["volume"] for k in buffer]
            }

            df = pd.DataFrame(df_data)

            logger.debug(f"[FEATURES] {symbol}: Calculating indicators from {len(df)} bars...")

            # Calculate indicators
            features = self.indicator_calculator.calculate_all(df)

            # Add activation threshold
            features["activation_threshold"] = settings.ACTIVATION_THRESHOLD

            # Cache features
            self._feature_cache[symbol] = features

            logger.debug(f"[FEATURES] {symbol}: {len(features)} indicators calculated")
            return features

        except Exception as e:
            logger.error(f"[FEATURES] {symbol}: Error - {e}")
            return None

    def _update_ohlcv_buffer(self, symbol: str, data: MarketData):
        """Update OHLCV buffer for a symbol"""

        kline_data = {
            "timestamp": data.timestamp,
            "open": data.open,
            "high": data.high,
            "low": data.low,
            "close": data.close,
            "volume": data.volume
        }

        self._ohlcv_buffers[symbol].append(kline_data)

        # Keep buffer size manageable
        max_buffer = 1000
        if len(self._ohlcv_buffers[symbol]) > max_buffer:
            self._ohlcv_buffers[symbol] = self._ohlcv_buffers[symbol][-max_buffer:]

    async def _execute_signal(self, signal: TradeSignal, price: float, quantity: float = None):
        """Execute an approved trading signal with position sizing"""

        symbol = signal.symbol
        logger.debug(f"[EXECUTE] {symbol}: Starting execution...")

        # Calculate position size using Turtle N-unit method if not provided
        if quantity is None or quantity <= 0:
            use_price = signal.suggested_price if signal.suggested_price > 0 else price
            logger.debug(f"[EXECUTE] {symbol}: Calculating position size...")
            pos_result = position_sizer.calculate_from_signal(
                equity=self._state.equity,
                signal=signal,
                current_price=use_price
            )

            if not pos_result.valid:
                logger.warning(f"[EXECUTE] {symbol}: Position sizing failed - {pos_result.reason}")
                return

            quantity = pos_result.quantity

            logger.info(
                f"[POSITION SIZE] {symbol}: "
                f"Equity={self._state.equity:.0f} | "
                f"Price={use_price:.2f} | "
                f"ATR={signal.atr:.4f} | "
                f"Qty={quantity:.3f} | "
                f"Value=${pos_result.position_value_usdt:.2f} | "
                f"Risk=${pos_result.risk_amount_usdt:.2f} ({pos_result.stop_distance_pct:.2f}%)"
            )

        # Minimum quantity check
        if quantity < 0.001:
            logger.warning(f"[EXECUTE] {symbol}: Quantity too small ({quantity})")
            return

        # Submit order
        logger.debug(f"[EXECUTE] {symbol}: Submitting order to Binance...")
        result = await self.order_manager.submit_order(
            signal=signal,
            quantity=quantity,
            price=price
        )

        if result.success:
            logger.info(
                f"[ORDER FILLED] {symbol} {signal.action} | "
                f"Qty={quantity:.3f} | Price=${price:.2f} | "
                f"OrderID={result.order_id}"
            )

            notification_manager.send_info(
                title="Trade Executed",
                message=f"{symbol} {signal.action}",
                quantity=f"{quantity:.3f}",
                price=f"{price:.2f}"
            )

            # Persist state
            state_manager.save_state(self._state)
        else:
            logger.error(f"[ORDER FAILED] {symbol}: {result.error_message}")

    async def _check_exits(self, symbol: str, data: MarketData, features: Dict):
        """
        Açık pozisyonlar için exit kontrolü

        Her kline close'da çağrılır
        """

        position = self._state.open_positions.get(symbol)
        if not position:
            return

        # Position'u güncelle (current price)
        old_price = position.current_price
        position.current_price = data.close

        # Unrealized PnL hesapla
        if position.side == "LONG":
            position.unrealized_pnl = (data.close - position.entry_price) * position.quantity
        else:
            position.unrealized_pnl = (position.entry_price - data.close) * position.quantity

        pnl_pct = 0
        if position.side == "LONG":
            pnl_pct = (data.close - position.entry_price) / position.entry_price * 100
        else:
            pnl_pct = (position.entry_price - data.close) / position.entry_price * 100

        logger.debug(
            f"[POSITION UPDATE] {symbol} {position.side}: "
            f"Entry={position.entry_price:.2f} | "
            f"Old={old_price:.2f} | New={data.close:.2f} | "
            f"PnL=${position.unrealized_pnl:.2f} ({pnl_pct:+.2f}%)"
        )

        # Exit kontrolü
        exit_signal = exit_manager.check_exit(
            position=position,
            features=features,
            symbol=symbol
        )

        if exit_signal.should_exit:
            logger.info(
                f"[EXIT TRIGGERED] {symbol} | Type: {exit_signal.exit_type} | "
                f"Urgency: {exit_signal.urgency} | "
                f"Reason: {exit_signal.reason}"
            )

            # Pozisyonu kapat
            await self._close_position(symbol, exit_signal)
        else:
            logger.debug(f"[EXIT] {symbol}: No exit signal (holding position)")

    async def _close_position(self, symbol: str, exit_signal: ExitSignal = None):
        """
        Pozisyon kapatma metodu (geliştirilmiş)

        Args:
            symbol: Trading sembolü
            exit_signal: Exit sinyali (opsiyonel)
        """

        if symbol not in self._state.open_positions:
            logger.warning(f"[CLOSE] {symbol}: No position found")
            return

        position = self._state.open_positions[symbol]

        # Exit urgency kontrolü
        urgency = exit_signal.urgency if exit_signal else "NEXT_BAR"

        # PnL hesapla
        pnl_amount = position.unrealized_pnl
        pnl_pct = 0
        if position.side == "LONG":
            pnl_pct = (position.current_price - position.entry_price) / position.entry_price * 100
        else:
            pnl_pct = (position.entry_price - position.current_price) / position.entry_price * 100

        hold_duration = (datetime.now(timezone.utc) - position.entry_time).total_seconds() / 3600

        logger.info("=" * 80)
        logger.info(
            f"[POSITION CLOSE] {symbol} {position.side}\n"
            f"  Entry:     ${position.entry_price:.2f}\n"
            f"  Exit:      ${position.current_price:.2f}\n"
            f"  PnL:       ${pnl_amount:+.2f} ({pnl_pct:+.2f}%)\n"
            f"  Exit Type: {exit_signal.exit_type if exit_signal else 'MANUAL'}\n"
            f"  Urgency:   {urgency}\n"
            f"  Duration:  {hold_duration:.1f} hours\n"
            f"  Reason:    {exit_signal.reason if exit_signal else 'Manual close'}"
        )
        logger.info("=" * 80)

        # Performance tracking
        self._state.total_trades += 1
        if pnl_amount > 0:
            self._state.winning_trades += 1
            logger.info(f"[PERF] {symbol}: WINNER (${pnl_amount:+.2f}) | Win Rate: {self._state.winning_trades}/{self._state.total_trades}")
        else:
            self._state.losing_trades += 1
            logger.info(f"[PERF] {symbol}: LOSER (${pnl_amount:+.2f}) | Win Rate: {self._state.winning_trades}/{self._state.total_trades}")

        # Exit type'e göre urgency belirle
        if urgency == "IMMEDIATE":
            logger.debug(f"[CLOSE] {symbol}: Immediate execution")
            # Hemen kapat (dry-run'da simüle et)
            if not self.order_manager.dry_run:
                result = await self.order_manager.close_position(symbol, position)
            else:
                result = type('obj', (object,), {'success': True})()
        else:
            logger.debug(f"[CLOSE] {symbol}: Next bar execution")
            # Sonraki bar'da kapat
            if not self.order_manager.dry_run:
                result = await self.order_manager.close_position(symbol, position)
            else:
                result = type('obj', (object,), {'success': True})()

        if result.success:
            logger.info(f"[CLOSE SUCCESS] {symbol}: Position closed")
        else:
            logger.error(f"[CLOSE FAILED] {symbol}: {result.error_message}")

        # State'den çıkar
        del self._state.open_positions[symbol]

        # State'i kaydet
        state_manager.save_state(self._state)

        # Detaylı bildirim
        notification_manager.send_info(
            title="Position Closed",
            message=f"{symbol} {position.side} position closed",
            exit_type=exit_signal.exit_type if exit_signal else "MANUAL",
            exit_reason=exit_signal.reason if exit_signal else "Manual close",
            pnl_usdt=f"{pnl_amount:.2f}",
            pnl_pct=f"{pnl_pct:+.2f}%",
            entry_price=f"{position.entry_price:.2f}",
            exit_price=f"{position.current_price:.2f}",
            hold_duration_hours=f"{hold_duration:.1f}"
        )

    async def _on_error_event(self, error: Exception):
        """Handle WebSocket errors"""

        logger.error(f"[WS ERROR] WebSocket error: {error}")

        notification_manager.send_error(
            title="WebSocket Error",
            message=str(error)
        )

    def get_latency_metrics(self) -> LatencyMetrics:
        """Get current latency metrics"""
        return self.ws_collector.get_latency_metrics()

    def get_system_state(self) -> Optional[SystemState]:
        """Get current system state"""
        return self._state
