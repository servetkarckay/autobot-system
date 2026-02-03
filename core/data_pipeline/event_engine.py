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

from core.data_pipeline.websocket_collector import WebSocketCollector, MarketData, LatencyMetrics
from core.data_pipeline.data_validator import DataValidator
from core.metadata.static_metadata_engine import StaticMetadataEngine
from core.feature_engine.incremental_indicators import IncrementalIndicatorCalculator, IncrementalEMA
from core.feature_engine.indicators import IndicatorCalculator
from core.feature_engine.regime_detector import RegimeDetector
from core.decision.rule_engine import RuleEngine
from core.decision.bias_generator import BiasAggregator
from core.risk.pre_trade_veto import PreTradeVetoChain, VetoConfig
from core.risk.position_sizer import position_sizer
from core.execution.order_manager import OrderManager
from core.execution.exit_manager import exit_manager, ExitSignal
from core.risk.adx_entry_gate import adx_entry_gate
from core.state_manager import state_manager
from core.state_manager import SystemState, SystemStatus, MarketRegime, TradeSignal, Position
from config.settings import settings
from core.notifier import notification_manager, NotificationPriority
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

        # Feature calculation (New Incremental Calculator)
        self.indicator_calculator: Optional[IncrementalIndicatorCalculator] = None
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
        
        # Metadata engine for exchange rules
        self.metadata_engine = StaticMetadataEngine()

        # System state
        self._state: Optional[SystemState] = None

        # Feature cache (per symbol)
        self._feature_cache: Dict[str, Dict] = defaultdict(dict)

        # OHLCV data buffers (for indicator calculation)
        self._ohlcv_buffers: Dict[str, list] = defaultdict(list)

        # Decision throttling (avoid excessive decisions)
        self._last_decision_time: Dict[str, datetime] = {}
        self._min_decision_interval_seconds = 1  # Max one decision per second per symbol
        self._min_decision_interval_book = 30  # 30 seconds for book ticker events
        
        # Real-time price tracking (from book ticker)
        self._realtime_prices: Dict[str, float] = {}
        
        # Decision throttling - separate for kline and book ticker
        self._min_decision_interval_book = 30  # 30 seconds for book ticker events

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

        # Kline events update OHLCV data
        self.ws_collector.on_kline(self._on_kline_event)

        # Book ticker events trigger continuous signal evaluation
        self.ws_collector.on_book_ticker(self._on_book_ticker_event)

        # Error handling
        self.ws_collector.on_error(self._on_error_event)


    def _calculate_adaptive_stop_loss(self, entry_price, atr, side, volatility_regime):
        if volatility_regime == 'HIGH':
            mult = settings.MAX_STOP_LOSS_MULTIPLIER
        elif volatility_regime == 'LOW':
            mult = settings.MIN_STOP_LOSS_MULTIPLIER
        else:
            mult = settings.STOP_LOSS_ATR_MULTIPLIER
        if side == 'LONG':
            return entry_price - (mult * atr)
        else:
            return entry_price + (mult * atr)

    def _update_trailing_stop(self, position, current_price, atr):
        if position.side == 'LONG':
            pct = (current_price - position.entry_price) / position.entry_price * 100
        else:
            pct = (position.entry_price - current_price) / position.entry_price * 100
        if pct > position.highest_profit_pct:
            position.highest_profit_pct = pct
        if pct >= position.trailing_stop_activation_pct:
            if pct >= settings.BREAK_EVEN_PCT and not position.break_even_triggered:
                position.stop_loss_price = position.entry_price
                position.break_even_triggered = True
                logger.info('[BREAK-EVEN] ' + str(position.symbol) + ': Stop at entry')
            elif position.break_even_triggered:
                extra = pct - settings.BREAK_EVEN_PCT
                adj = extra * settings.TRAILING_STOP_RATE / 100
                if position.side == 'LONG':
                    new_sl = position.entry_price + (position.entry_price * adj)
                    if new_sl > position.stop_loss_price:
                        position.stop_loss_price = new_sl
                else:
                    new_sl = position.entry_price - (position.entry_price * adj)
                    if new_sl < position.stop_loss_price:
                        position.stop_loss_price = new_sl

    async def start(self, symbols: list):
        """Start the event-driven trading engine"""

        logger.info("=" * 60)
        logger.info(f"[ENGINE] Starting trading engine for {len(symbols)} symbols")
        logger.info(f"[ENGINE] Symbols: {symbols[:10]}..." if len(symbols) > 10 else f"[ENGINE] Symbols: {symbols}")
        logger.info("=" * 60)

        # Initialize the incremental calculator with symbols
        self.indicator_calculator = IncrementalIndicatorCalculator(symbols)
        for symbol in symbols:
            self.indicator_calculator.add_indicator(symbol, 'EMA_20', IncrementalEMA(period=20))
            self.indicator_calculator.add_indicator(symbol, 'EMA_50', IncrementalEMA(period=50))

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

        # Reconcile positions with the exchange before starting
        await self._reconcile_positions(symbols)

        # Load historical data and seed indicators
        await self._load_historical_data_and_seed_indicators(symbols)

        # Subscribe to data streams after seeding
        self.ws_collector.subscribe_klines(symbols, interval="15m")
        self.ws_collector.subscribe_book_ticker(symbols)

        # Start WebSocket and event loop
        await self.ws_collector.start()


    async def _reconcile_positions(self, symbols: list[str]):
        """Compare local state with exchange positions and sync them."""
        logger.info("[RECONCILE] Starting position reconciliation...")

        try:
            # Fetch current open positions from the exchange
            exchange_positions = await self.order_manager.get_open_positions(symbols)
            local_positions = self._state.open_positions

            logger.info(f"[RECONCILE] Found {len(exchange_positions)} positions on exchange and {len(local_positions)} in local state.")

            # 1. Check for positions on the exchange that are NOT in the local state
            for symbol, pos_data in exchange_positions.items():
                if symbol not in local_positions:
                    logger.warning(f"[RECONCILE] Found position for {symbol} on exchange but not in local state. ADDING to state.")
                    
                    quantity = float(pos_data.get("positionAmt", 0))
                    position = Position(
                        symbol=symbol,
                        side="LONG" if quantity > 0 else "SHORT",
                        entry_price=float(pos_data.get("entryPrice", 0)),
                        quantity=abs(quantity),
                        current_price=float(pos_data.get("markPrice", 0)),
                        entry_time=datetime.fromtimestamp(int(pos_data.get("updateTime", 0)) / 1000, tz=timezone.utc),
                        # Stop-loss and other metadata will be default, needs monitoring to adjust
                    )
                    self._state.open_positions[symbol] = position
                    notification_manager.send_warning(
                        title="Position Reconciled",
                        message=f"Found and synced a {position.side} position for {symbol} from the exchange."
                    )

            # 2. Check for positions in the local state that are NOT on the exchange
            local_symbols = list(local_positions.keys())
            for symbol in local_symbols:
                if symbol not in exchange_positions:
                    logger.warning(f"[RECONCILE] Found position for {symbol} in local state but not on exchange. REMOVING from state.")
                    del self._state.open_positions[symbol]
            
            state_manager.save_state(self._state)
            logger.info("[RECONCILE] Position reconciliation complete.")

        except Exception as e:
            logger.error(f"[RECONCILE] Error during position reconciliation: {e}", exc_info=True)
            notification_manager.send_critical(title="Reconciliation Failed", message=str(e))

    async def _on_kline_event(self, data: MarketData):
        """Handle kline event - update OHLCV buffer"""

        # Validate data first
        is_valid, reason = self.data_validator.validate(data)
        if not is_valid:
            logger.debug(f"[DATA] {data.symbol}: Rejected - {reason}")
            return

        # Update OHLCV buffer
        self._update_ohlcv_buffer(data.symbol, data)
        
        # Update real-time price
        self._realtime_prices[data.symbol] = data.close

        # Trigger evaluation on kline close
        if data.is_kline_closed:
            logger.debug(f"[KLINE CLOSED] {data.symbol}: Triggering evaluation")
            await self._evaluate_signal(data.symbol, data.close, trigger="kline_close")


    def _cleanup_feature_cache(self):
        """Clean up old feature cache entries to prevent memory leak"""
        max_cache_entries = 100  # Keep only last 100 symbols
        if len(self._feature_cache) > max_cache_entries:
            # Remove oldest entries (first half)
            items_to_remove = list(self._feature_cache.keys())[:max_cache_entries // 2]
            for key in items_to_remove:
                del self._feature_cache[key]
            logger.debug(f"[CLEANUP] Removed {len(items_to_remove)} old feature cache entries")

    async def _evaluate_signal(self, symbol: str, price: float, trigger: str = "unknown"):
        """Evaluate signal with throttling - works for both kline and book ticker events"""

        now = datetime.now(timezone.utc)

        # Check throttling based on trigger type
        last_time = self._last_decision_time.get(symbol)
        
        if trigger == "book_ticker":
            min_interval = self._min_decision_interval_book
        else:  # kline_close
            min_interval = self._min_decision_interval_seconds

        if last_time:
            elapsed = (now - last_time).total_seconds()
            if elapsed < min_interval:
                logger.debug(f"[THROTTLE] {symbol}: Skipped ({elapsed:.1f}s < {min_interval}s) trigger={trigger}")
                return

        self._last_decision_time[symbol] = now

        # Log evaluation trigger (only for kline close to reduce noise)
        if trigger == "kline_close":
            logger.info("=" * 80)
            logger.info(f"[EVALUATE] {symbol} @ {price:.2f} | Trigger: {trigger} | Has Position: {symbol in self._state.open_positions}")
            logger.info("=" * 80)
        else:
            logger.debug(f"[EVALUATE] {symbol} @ {price:.2f} | Trigger: {trigger}")

        # Step 1: Calculate features
        logger.debug(f"[STEP 1] {symbol}: Calculating features...")
        features = await self._calculate_features(symbol, price, trigger)

        if not features:
            logger.warning(f"[STEP 1] {symbol}: No features calculated (insufficient data)")
            return

        # Add timestamp for exit manager
        features["timestamp"] = int(now.timestamp() * 1000)

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
        try:
            old_regime = self._state.get_symbol_regime(symbol)
        except RuntimeError:
            # First time detecting regime for this symbol
            old_regime = MarketRegime.UNKNOWN
        self._state.update_symbol_regime(symbol, current_regime)
        self._state.current_regime = current_regime  # Legacy global regime
        self._state.last_update = now

        # Update exit manager with symbol regime
        exit_manager.update_symbol_regime(symbol, current_regime)

        if old_regime != current_regime and old_regime != MarketRegime.UNKNOWN:
            logger.warning(f"[REGIME CHANGE] {symbol}: {old_regime.value} → {current_regime.value}")

        # Update exit manager with ADX (for momentum loss exit)
        exit_manager.update_symbol_adx(symbol, features.get("adx", 0), int(now.timestamp() * 1000))
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

        # Step 4: ADX Entry Gate (Chop Filter)
        if signal.action in ["PROPOSE_LONG", "PROPOSE_SHORT"]:
            logger.debug(f"[STEP 4] {symbol}: Running ADX entry gate...")
            
            adx_result = adx_entry_gate.check(signal, features, symbol)
            
            if not adx_result.approved:
                logger.warning(f"[ADX GATE REJECTED] {symbol}: {adx_result.veto_reason}")
                
                notification_manager.send_warning(
                    title="Trade Blocked - Chop Filter",
                    message=adx_result.veto_reason,
                    symbol=symbol,
                    stage="adx_entry_gate",
                    adx=f"{features.get('adx', 0):.1f}"
                )
                return  # Skip veto chain and execution
            
            logger.info(f"[ADX GATE PASSED] {symbol}: Trend confirmed, proceeding to veto chain")
        
        # Step 5: Apply Risk Veto Chain
        if signal.action in ["PROPOSE_LONG", "PROPOSE_SHORT"]:
            logger.debug(f"[STEP 5] {symbol}: Running veto chain...")

            # Calculate position size (simplified - would use proper sizing logic)
            proposed_quantity = None  # Let position_sizer calculate it

            veto_result = self.veto_chain.evaluate(
                signal=signal,
                state=self._state,
                proposed_quantity=proposed_quantity,
                proposed_price=price
            )

            logger.debug(
                f"[VETO] {symbol}: {veto_result.veto_stage if not veto_result.approved else 'PASSED'} | "
                f"Approved: {veto_result.approved}"
            )

            if veto_result.approved:
                # Step 6: Execute approved signal
                logger.debug(f"[STEP 6] {symbol}: Executing signal...")
                await self._execute_signal(signal, price, 0.0)
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
            await self._check_exits(symbol, price, features)
        else:
            logger.debug(f"[STEP EXIT] {symbol}: No open position, skip exit check")

    async def _on_book_ticker_event(self, data: MarketData):
        """Handle book ticker event - continuous scanning"""

        # Get mid price from bid/ask
        if data.best_bid and data.best_ask:
            mid_price = (data.best_bid + data.best_ask) / 2
        elif data.best_bid:
            mid_price = data.best_bid
        elif data.best_ask:
            mid_price = data.best_ask
        else:
            return  # No valid price

        # Update real-time price
        old_price = self._realtime_prices.get(data.symbol)
        self._realtime_prices[data.symbol] = mid_price

        # Only log if price changed significantly (>0.01%)
        if old_price is None or abs(mid_price - old_price) / old_price > 0.0001:
            logger.debug(f"[BOOK TICKER] {data.symbol}: {mid_price:.2f} (bid={data.best_bid:.2f}, ask={data.best_ask:.2f})")

        # Trigger signal evaluation with throttling
        await self._evaluate_signal(data.symbol, mid_price, trigger="book_ticker")

    async def _calculate_features(self, symbol: str, price: float, trigger: str) -> Optional[Dict]:
        """
        Calculate technical features using the incremental calculator.
        - For 'book_ticker' triggers, only update fast, incremental indicators.
        - For 'kline_close' triggers, update all indicators.
        """
        if not self.indicator_calculator or not self.indicator_calculator.is_seeded(symbol):
            logger.debug(f"[FEATURES] {symbol}: Calculator not ready or not seeded.")
            return None

        buffer = self._ohlcv_buffers.get(symbol)
        if not buffer:
            return None
        
        try:
            import pandas as pd
            # Create DataFrame from buffer for complex indicators
            df_data = {
                "open": [k["open"] for k in buffer], "high": [k["high"] for k in buffer],
                "low": [k["low"] for k in buffer], "close": [k["close"] for k in buffer],
                "volume": [k["volume"] for k in buffer]
            }
            df = pd.DataFrame(df_data)

            # Always update the last candle's close price with the real-time price
            df.loc[df.index[-1], "close"] = price
            
            # Use the new calculator
            features = self.indicator_calculator.calculate_features(
                symbol,
                new_price=price,
                full_data=df  # Provide the full dataframe for non-incremental indicators
            )
            
            # Use safe IndicatorCalculator (replaces unreliable pandas_ta)
            safe_calc = IndicatorCalculator()
            safe_features = safe_calc.calculate_all(df)
            
            # Merge features (safe calculator provides all indicators)
            for k, v in safe_features.items():
                if k not in features:
                    features[k] = v
            
            # Add breakout detection
            features['breakout_20_long'] = price > features.get('high_20', 0)
            features['breakout_20_short'] = price < features.get('low_20', 0)
            logger.debug(f'[FEATURES] {symbol}: safe_calc - adx={features.get("adx", 0):.1f}')
            # ---


            # Merge incremental calculator results (uppercase keys to lowercase)
            if 'EMA_20' in features:
                features['ema_20'] = features['EMA_20']
            if 'EMA_50' in features:
                features['ema_50'] = features['EMA_50']
            
            # Calculate ema_20_above_ema_50 for trend rules
            features['ema_20_above_ema_50'] = features.get('ema_20', 0) > features.get('ema_50', 0)
            
            # Calculate Bollinger Bands middle for combo rules
            bb_result = ta.bbands(df["close"], length=20)
            if bb_result is not None and not bb_result.empty:
                df = pd.concat([df, bb_result], axis=1)
                features['bb_middle'] = df['BBL_20_2.0'].iloc[-1] if 'BBL_20_2.0' in df else price
            else:
                features['bb_middle'] = price

            
            features["activation_threshold"] = settings.ACTIVATION_THRESHOLD
            self._feature_cache[symbol] = features
            return features

        except Exception as e:
            logger.error(f"[FEATURES] {symbol}: Error in new calculation - {e}", exc_info=True)
            return None

    async def _load_historical_data_and_seed_indicators(self, symbols: list):
        """Load historical kline data and use it to seed the incremental indicators."""
        import aiohttp
        import pandas as pd
        
        logger.info("[HISTORICAL] Loading historical data and seeding indicators...")
        
        for symbol in symbols:
            try:
                # Fetch historical data (same as before)
                interval = "15m"
                limit = 500  # Need enough data for 20-period indicators for indicator seeding
                end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
                
                if settings.BINANCE_TESTNET:
                    url = f"https://testnet.binancefuture.com/fapi/v1/klines"
                else:
                    url = f"https://fapi.binance.com/fapi/v1/klines"
                
                params = {"symbol": symbol, "interval": interval, "limit": limit, "endTime": end_time}
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as resp:
                        data = await resp.json()
                
                if not isinstance(data, list) or len(data) < 50:
                    logger.warning(f"[HISTORICAL] {symbol}: Failed to load sufficient data ({len(data)} bars)")
                    continue
                
                # Populate OHLCV buffer
                for k in data:
                    kline_data = {
                        "timestamp": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                        "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                        "close": float(k[4]), "volume": float(k[5])
                    }
                    self._ohlcv_buffers[symbol].append(kline_data)
                
                # Create DataFrame for seeding
                df_data = {
                    "open": [k["open"] for k in self._ohlcv_buffers[symbol]],
                    "high": [k["high"] for k in self._ohlcv_buffers[symbol]],
                    "low": [k["low"] for k in self._ohlcv_buffers[symbol]],
                    "close": [k["close"] for k in self._ohlcv_buffers[symbol]],
                    "volume": [k["volume"] for k in self._ohlcv_buffers[symbol]]
                }
                df = pd.DataFrame(df_data)

                # Seed the indicators for the symbol
                self.indicator_calculator.seed_indicators(symbol, df)
                
                logger.info(
                    f"[HISTORICAL] {symbol}: Loaded and seeded with {len(df)} bars. "
                    f"Seeded: {self.indicator_calculator.is_seeded(symbol)}"
                )
                
                await asyncio.sleep(0.1)  # Rate limiting
                
            except Exception as e:
                logger.error(f"[HISTORICAL] {symbol}: Error during data loading/seeding - {e}", exc_info=True)
        
        logger.info(f"[HISTORICAL] Completed loading for {len(symbols)} symbols")

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

        # KRITIK FIX: Check if existing position exists (same or opposite side)
        new_side = "LONG" if "LONG" in signal.action else "SHORT"
        if symbol in self._state.open_positions:
            existing_position = self._state.open_positions[symbol]
            
            if existing_position.side == new_side:
                # Same side - position already exists, skip this signal
                logger.info(
                    f"[POSITION EXISTS] {symbol}: {new_side} position already open, "
                    f"skipping duplicate signal. Entry: {existing_position.entry_price:.5f}, "
                    f"Current: {price:.5f}"
                )
                return
            
            # Opposite side - need to close first
            logger.warning(
                f"[POSITION CONFLICT] {symbol}: Cannot open {new_side} while {existing_position.side} exists. "
                f"Closing existing position and canceling open orders..."
            )
            
            # KRITIK FIX: Cancel any pending orders for this symbol
            try:
                open_orders = await self.order_manager.get_open_orders(symbol)
                if open_orders and len(open_orders) > 0:
                    logger.warning(f"[CANCEL ORDERS] {symbol}: Found {len(open_orders)} open orders, canceling...")
                    for order in open_orders:
                        order_id = order.get('orderId')
                        if order_id:
                            await self.order_manager.cancel_order(str(order_id), symbol)
                            logger.info(f"[CANCEL ORDERS] {symbol}: Canceled order {order_id}")
                else:
                    logger.debug(f"[CANCEL ORDERS] {symbol}: No open orders to cancel")
            except Exception as e:
                logger.error(f"[CANCEL ORDERS] {symbol}: Error canceling orders: {e}")
            
            await self._close_position(symbol)
            logger.info(f"[POSITION CONFLICT] {symbol}: Old position closed, proceeding with {new_side}")


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

            # KRITIK FIX: Create Position object after order fill
            position_side = "LONG" if "LONG" in signal.action else "SHORT"

            # Calculate stop loss (2N from entry)
            atr = signal.atr if signal.atr and signal.atr > 0 else 0.0001
            if position_side == "LONG":
                stop_loss = price - (2 * atr)
            else:
                stop_loss = price + (2 * atr)

            # Import ExitMetadata
            from core.state_manager import ExitMetadata

            # Create Position object with exit_metadata
            position = Position(
                symbol=symbol,
                side=position_side,
                entry_price=price,
                quantity=quantity,
                current_price=price,
                stop_loss_price=stop_loss,
                initial_stop_loss=stop_loss,
                highest_profit_pct=0.0,
                break_even_triggered=False,
                trailing_stop_activation_pct=settings.TRAILING_STOP_ACTIVATION_PCT,
                entry_time=datetime.now(timezone.utc),
                regime_at_entry=self._state.current_regime,
                unrealized_pnl=0.0,
                exit_metadata=ExitMetadata()  # Initialize with empty metadata
            )

            # BINANCE STOP LOSS EMRİ GÖNDER - Pozisyon açıldığında
            stop_result = await self.order_manager.submit_stop_loss_order(
                symbol=symbol,
                position_side=position_side,
                stop_price=stop_loss,
                quantity=quantity
            )
            
            if stop_result.success:
                position.stop_order_id = stop_result.order_id
                logger.info(f"[STOP ORDER SET] {symbol}: stop_order_id={stop_result.order_id}")
            else:
                logger.warning(f"[STOP ORDER FAILED] {symbol}: {stop_result.error_message} - Position without exchange protection!")

            # Add to state
            self._state.open_positions[symbol] = position

            logger.info(
                f"[POSITION OPENED] {symbol} {position_side} | "
                f"Entry=${price:.4f} | Qty={quantity:.3f} | "
                f"Stop Loss=${stop_loss:.4f} | "
                f"Open Positions: {len(self._state.open_positions)}"
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

    async def _check_exits(self, symbol: str, price: float, features: Dict):
        """
        Açık pozisyonlar için exit kontrolü
        
        Continuous evaluation - her book ticker event'inde çağrılabilir
        """

        position = self._state.open_positions.get(symbol)
        if not position:
            return

        # Position'u güncelle (current price)
        old_price = position.current_price
        position.current_price = price
        
        # TRAILING STOP GÜNCELLEME - Her fiyat değişiminde çalıştır
        atr = features.get("atr", 0)
        old_stop = position.stop_loss_price  # Save for comparison
        if atr > 0:
            self._update_trailing_stop(position, price, atr)
            logger.debug(f"[TRAILING STOP] {symbol}: SL=${position.stop_loss_price:.4f} | Highest Profit={position.highest_profit_pct:.2f}% | Break-Even={position.break_even_triggered}")
            
            # Stop değiştiyse Binance"a güncelle
            if position.stop_loss_price != old_stop and position.stop_loss_price is not None:
                await self.order_manager.update_stop_loss(
                    symbol=symbol,
                    position_side=position.side,
                    new_stop_price=position.stop_loss_price,
                    quantity=position.quantity
                )

        # Unrealized PnL hesapla
        if position.side == "LONG":
            position.unrealized_pnl = (price - position.entry_price) * position.quantity
        else:
            position.unrealized_pnl = (position.entry_price - price) * position.quantity

        pnl_pct = 0
        if position.side == "LONG":
            pnl_pct = (price - position.entry_price) / position.entry_price * 100
        else:
            pnl_pct = (position.entry_price - price) / position.entry_price * 100

        logger.debug(
            f"[POSITION UPDATE] {symbol} {position.side}: "
            f"Entry={position.entry_price:.2f} | "
            f"Old={old_price:.2f} | New={price:.2f} | "
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
