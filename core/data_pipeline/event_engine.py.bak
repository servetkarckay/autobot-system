"""
AUTOBOT Data Pipeline - Event Engine
Orchestrates event-driven decision making from WebSocket data
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
        logger.info("TradingDecisionEngine initialized")
    
    def _register_event_handlers(self):
        """Register callbacks for WebSocket events"""
        
        # Kline close events trigger decisions
        self.ws_collector.on_kline(self._on_kline_event)
        
        # Error handling
        self.ws_collector.on_error(self._on_error_event)
    
    async def start(self, symbols: list):
        """Start the event-driven trading engine"""
        
        # Load system state
        self._state = state_manager.load_state()
        if not self._state:
            self._state = SystemState(
                status=SystemStatus.RUNNING,
                equity=10000.0,
                peak_equity=10000.0
            )
            logger.info("Created new system state")
        
        # Subscribe to data streams
        self.ws_collector.subscribe_klines(symbols, interval="1m")
        self.ws_collector.subscribe_book_ticker(symbols)
        
        logger.info(f"Starting trading engine for {len(symbols)} symbols")
        
        # Start WebSocket and event loop
        await self.ws_collector.start()
    
    async def _on_kline_event(self, data: MarketData):
        """Handle kline event (event-driven trigger)"""
        
        # Validate data first
        is_valid, reason = self.data_validator.validate(data)
        if not is_valid:
            logger.debug(f"Data rejected: {reason}")
            return
        
        # Update OHLCV buffer
        self._update_ohlcv_buffer(data.symbol, data)
        
        # Only make decisions on kline close
        if data.is_kline_closed:
            await self._on_kline_close(data)
    
    async def _on_kline_close(self, data: MarketData):
        """Handle kline close event - DECISION TRIGGER"""
        
        symbol = data.symbol
        
        # Check throttling
        now = datetime.now(timezone.utc)
        last_time = self._last_decision_time.get(symbol)
        
        if last_time:
            elapsed = (now - last_time).total_seconds()
            if elapsed < self._min_decision_interval_seconds:
                logger.debug(f"Decision throttled for {symbol}: {elapsed:.2f}s since last")
                return
        
        self._last_decision_time[symbol] = now
        
        logger.info(f"KLINE CLOSE TRIGGER: {symbol} @ {data.close}")
        
        # Step 1: Calculate features
        features = await self._calculate_features(symbol)
        
        if not features:
            logger.warning(f"No features calculated for {symbol}")
            return
        
        # Step 2: Detect regime
        current_regime = self.regime_detector.detect(features)
        volatility_regime = self.regime_detector.detect_volatility(features)
        
        logger.info(f"{symbol} Regime: {current_regime.value} Volatility: {volatility_regime.value}")
        
        # Update system state
        self._state.current_regime = current_regime
        self._state.last_update = now
        
        # Step 3: Generate signal from Decision Engine
        signal = self.rule_engine.evaluate(
            symbol=symbol,
            current_regime=current_regime,
            features=features,
            strategy_name="default"
        )
        
        logger.info(f"Signal generated: {symbol} {signal.action} bias={signal.bias_score:.3f}")
        
        # Step 4: Apply Risk Veto Chain
        if signal.action in ["PROPOSE_LONG", "PROPOSE_SHORT"]:
            
            # Calculate position size (simplified - would use proper sizing logic)
            proposed_quantity = None  # Let position_sizer calculate it
            
            veto_result = self.veto_chain.evaluate(
                signal=signal,
                state=self._state,
                proposed_quantity=proposed_quantity,
                proposed_price=data.close
            )
            
            if veto_result.approved:
                # Step 5: Execute approved signal
                await self._execute_signal(signal, data.close, 0.0)
            else:
                logger.warning(f"Signal vetoed: {veto_result.veto_reason} at {veto_result.veto_stage}")
                
                notification_manager.send_warning(
                    title="Trade Vetoed",
                    message=veto_result.veto_reason,
                    symbol=symbol,
                    stage=veto_result.veto_stage
                )
        elif signal.action == "CLOSE":
            # Close existing position
            await self._close_position(symbol)
    
    async def _calculate_features(self, symbol: str) -> Optional[Dict]:
        """Calculate technical features for a symbol"""
        
        buffer = self._ohlcv_buffers.get(symbol)
        if not buffer or len(buffer) < 50:
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
            
            # Calculate indicators
            features = self.indicator_calculator.calculate_all(df)
            
            # Add activation threshold
            features["activation_threshold"] = settings.ACTIVATION_THRESHOLD
            
            # Cache features
            self._feature_cache[symbol] = features
            
            return features
            
        except Exception as e:
            logger.error(f"Error calculating features for {symbol}: {e}")
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
        
        # Calculate position size using Turtle N-unit method if not provided
        if quantity is None or quantity <= 0:
            use_price = signal.suggested_price if signal.suggested_price > 0 else price
            pos_result = position_sizer.calculate_from_signal(
                equity=self._state.equity,
                signal=signal,
                current_price=use_price
            )
            
            if not pos_result.valid:
                logger.warning(f"Position sizing failed for {signal.symbol}: {pos_result.reason}")
                return
            
            quantity = pos_result.quantity
            
            logger.info(
                f"Position sizing {signal.symbol}: equity={self._state.equity:.0f}, "
                f"price={use_price:.2f}, atr={signal.atr:.4f} -> qty={quantity:.3f}, "
                f"value={pos_result.position_value_usdt:.2f}, risk={pos_result.risk_amount_usdt:.2f}"
            )
        
        # Minimum quantity check
        if quantity < 0.001:
            logger.warning(f"Calculated quantity too small for {signal.symbol}: {quantity}")
            return
        
        # Submit order
        result = await self.order_manager.submit_order(
            signal=signal,
            quantity=quantity,
            price=price
        )
        
        if result.success:
            logger.info(f"Order submitted: {signal.symbol} {signal.action} qty={quantity:.3f} @ {price:.2f}")
            
            notification_manager.send_info(
                title="Trade Executed",
                message=f"{signal.symbol} {signal.action}",
                quantity=f"{quantity:.3f}",
                price=f"{price:.2f}"
            )
            
            # Persist state
            state_manager.save_state(self._state)
        else:
            logger.error(f"Order failed: {result.error_message}")
    
    async def _close_position(self, symbol: str):
        """Close position for a symbol"""
        
        if symbol in self._state.open_positions:
            logger.info(f"Closing position: {symbol}")
            
            # Would submit market order to close
            # ...
            
            # Remove from state
            del self._state.open_positions[symbol]
            state_manager.save_state(self._state)
    
    async def _on_error_event(self, error: Exception):
        """Handle WebSocket errors"""
        
        logger.error(f"WebSocket error: {error}")
        
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
