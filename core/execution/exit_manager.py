"""
AUTOBOT Exit Manager - Production Ready v1.2
Donchian + ADX Momentum Exit Strategy

FIXES:
1. ADX düşüş kontrolü (adx_prev > adx)
2. Sembol bazlı regime takibi
3. Bar başına tek exit kontrolü
4. Thread-safe operations with locks
5. Improved NaN/Infinity protection
"""
import logging
import math
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict
from datetime import datetime, timezone

from core.state_manager import Position, MarketRegime

logger = logging.getLogger("autobot.execution.exit")


@dataclass
class ExitSignal:
    """Exit sinyali"""
    should_exit: bool
    reason: str
    exit_type: str
    urgency: str


@dataclass
class ExitMetadata:
    """Exit metadata for position"""
    adx_at_entry: float = 0.0
    adx_prev: float = 0.0
    regime_at_entry: MarketRegime = MarketRegime.UNKNOWN
    last_exit_check_ts: Optional[int] = None


class ExitManager:
    """
    Donchian + ADX Momentum Exit - Production Version
    
    Thread-safe implementation with proper locking
    """

    def __init__(
        self,
        donchian_period: int = 20,
        adx_threshold: float = 20.0,
        min_r_profit: float = 1.0
    ):
        self.donchian_period = donchian_period
        self.adx_threshold = adx_threshold
        self.min_r_profit = min_r_profit

        self._symbol_regimes: Dict[str, MarketRegime] = {}
        self._symbol_adx_history: Dict[str, list] = {}
        
        # Thread safety locks
        self._regime_lock = threading.RLock()
        self._adx_lock = threading.RLock()
        self._exit_lock = threading.RLock()

        logger.info(f"[EXIT MANAGER] Initialized with thread-safety locks")

    def _is_valid_numeric(self, value: float) -> bool:
        """Check if value is valid finite number"""
        return isinstance(value, (int, float)) and math.isfinite(value) and not math.isnan(value)

    def update_symbol_regime(self, symbol: str, regime: MarketRegime):
        """Thread-safe symbol regime update"""
        with self._regime_lock:
            old_regime = self._symbol_regimes.get(symbol, MarketRegime.UNKNOWN)
            self._symbol_regimes[symbol] = regime
            if old_regime != regime:
                logger.debug(f"[EXIT REGIME] {symbol}: {old_regime.value} -> {regime.value}")

    def update_symbol_adx(self, symbol: str, adx: float, timestamp: int):
        """Thread-safe ADX update with validation"""
        if not self._is_valid_numeric(adx):
            logger.warning(f"[EXIT ADX] Invalid ADX for {symbol}: {adx}")
            return
            
        with self._adx_lock:
            if symbol not in self._symbol_adx_history:
                self._symbol_adx_history[symbol] = []
            
            history = self._symbol_adx_history[symbol]
            old_adx = history[-1][1] if history else None
            
            history.append((timestamp, adx))
            
            now = datetime.now(timezone.utc).timestamp() * 1000
            cutoff = now - 3600000
            self._symbol_adx_history[symbol] = [
                (ts, val) for ts, val in history if ts > cutoff and self._is_valid_numeric(val)
            ][:3]

    def _get_symbol_regime(self, symbol: str) -> MarketRegime:
        """Thread-safe regime getter"""
        with self._regime_lock:
            return self._symbol_regimes.get(symbol, MarketRegime.UNKNOWN)

    def _get_adx_trend(self, symbol: str, current_adx: float) -> str:
        """Get ADX trend with thread safety"""
        with self._adx_lock:
            history = self._symbol_adx_history.get(symbol, [])
            
            if len(history) < 2:
                return 'UNKNOWN'
            
            recent = history[-3:] if len(history) >= 3 else history
            
            all_falling = all(
                len(recent) > i + 1 and 
                self._is_valid_numeric(recent[i][1]) and 
                self._is_valid_numeric(recent[i+1][1]) and 
                recent[i][1] > recent[i+1][1] 
                for i in range(len(recent) - 1)
            )
            
            all_rising = all(
                len(recent) > i + 1 and 
                self._is_valid_numeric(recent[i][1]) and 
                self._is_valid_numeric(recent[i+1][1]) and 
                recent[i][1] < recent[i+1][1] 
                for i in range(len(recent) - 1)
            )
            
            if all_falling:
                return 'FALLING'
            elif all_rising:
                return 'RISING'
            return 'STABLE'

    def check_exit(
        self,
        position: Position,
        features: dict,
        symbol: str
    ) -> ExitSignal:
        """Thread-safe exit check"""
        with self._exit_lock:
            return self._check_exit_impl(position, features, symbol)

    def _check_exit_impl(
        self,
        position: Position,
        features: dict,
        symbol: str
    ) -> ExitSignal:
        close = features.get("close", 0)
        high_20 = features.get("high_20", 0)
        low_20 = features.get("low_20", 0)
        adx = features.get("adx", 0)
        bar_timestamp = features.get("timestamp", 0)

        if not all(self._is_valid_numeric(v) for v in [close, high_20, low_20, adx]):
            logger.warning(f"[EXIT CHECK] {symbol}: Invalid numeric values in features")
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        if not hasattr(position, 'exit_metadata'):
            position.exit_metadata = ExitMetadata()
            position.exit_metadata.regime_at_entry = position.regime_at_entry
            position.exit_metadata.adx_at_entry = adx

        metadata = position.exit_metadata

        now = datetime.now(timezone.utc)
        position_age_seconds = (now - position.entry_time).total_seconds()

        MIN_POSITION_AGE_SECONDS = 60
        if position_age_seconds < MIN_POSITION_AGE_SECONDS:
            logger.debug(f"[EXIT SKIP] {symbol}: Position too young ({position_age_seconds:.1f}s)")
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        if metadata.last_exit_check_ts and bar_timestamp <= metadata.last_exit_check_ts:
            logger.debug(f"[EXIT THROTTLE] {symbol}: Bar already checked")
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        metadata.last_exit_check_ts = bar_timestamp
        self.update_symbol_adx(symbol, adx, bar_timestamp)
        adx_trend = self._get_adx_trend(symbol, adx)
        symbol_regime = self._get_symbol_regime(symbol)

        stop_exit = self._check_stop_loss(position, close)
        if stop_exit.should_exit:
            return stop_exit

        regime_exit = self._check_regime_change(position, symbol_regime, symbol)
        if regime_exit.should_exit:
            return regime_exit

        momentum_exit = self._check_momentum_loss(position, features, close, adx, adx_trend)
        if momentum_exit.should_exit:
            return momentum_exit

        donchian_exit = self._check_donchian_break(position, features, close)
        if donchian_exit.should_exit:
            return donchian_exit

        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _check_stop_loss(self, position: Position, close: float) -> ExitSignal:
        if not position.stop_loss_price:
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        if position.side == "LONG" and close <= position.stop_loss_price:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss hit: {close:.2f} <= {position.stop_loss_price:.2f}",
                exit_type="STOP_LOSS",
                urgency="IMMEDIATE"
            )
        elif position.side == "SHORT" and close >= position.stop_loss_price:
            return ExitSignal(
                should_exit=True,
                reason=f"Stop loss hit: {close:.2f} >= {position.stop_loss_price:.2f}",
                exit_type="STOP_LOSS",
                urgency="IMMEDIATE"
            )
        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _check_regime_change(self, position: Position, current_regime: MarketRegime, symbol: str) -> ExitSignal:
        expected_regime = MarketRegime.BULL_TREND if position.side == "LONG" else MarketRegime.BEAR_TREND

        if position.side == "LONG" and current_regime != MarketRegime.BULL_TREND:
            return ExitSignal(
                should_exit=True,
                reason=f"Regime changed: BULL -> {current_regime.value}",
                exit_type="REGIME_CHANGE",
                urgency="IMMEDIATE"
            )
        elif position.side == "SHORT" and current_regime != MarketRegime.BEAR_TREND:
            return ExitSignal(
                should_exit=True,
                reason=f"Regime changed: BEAR -> {current_regime.value}",
                exit_type="REGIME_CHANGE",
                urgency="IMMEDIATE"
            )
        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _check_momentum_loss(self, position: Position, features: dict, close: float, adx: float, adx_trend: str) -> ExitSignal:
        if adx_trend != 'FALLING':
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        if adx >= self.adx_threshold:
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        atr = features.get("atr", 0)
        r_profit = self._calculate_r_profit(position, close, atr)

        if r_profit < self.min_r_profit:
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        high_20 = features.get("high_20", 0)
        low_20 = features.get("low_20", 0)

        if position.side == "LONG":
            in_donchian = close < high_20
            if in_donchian:
                return ExitSignal(
                    should_exit=True,
                    reason=f"Momentum loss: ADX={adx:.1f} (FALLING), R=+{r_profit:.2f}",
                    exit_type="MOMENTUM_LOSS",
                    urgency="NEXT_BAR"
                )
        elif position.side == "SHORT":
            in_donchian = close > low_20
            if in_donchian:
                return ExitSignal(
                    should_exit=True,
                    reason=f"Momentum loss: ADX={adx:.1f} (FALLING), R=+{r_profit:.2f}",
                    exit_type="MOMENTUM_LOSS",
                    urgency="NEXT_BAR"
                )

        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _check_donchian_break(self, position: Position, features: dict, close: float) -> ExitSignal:
        high_20 = features.get("high_20", 0)
        low_20 = features.get("low_20", 0)

        if position.side == "LONG":
            if close < low_20:
                return ExitSignal(
                    should_exit=True,
                    reason=f"Donchian break: {close:.2f} < {low_20:.2f}",
                    exit_type="DONCHIAN_BREAK",
                    urgency="NEXT_BAR"
                )
        elif position.side == "SHORT":
            if close > high_20:
                return ExitSignal(
                    should_exit=True,
                    reason=f"Donchian break: {close:.2f} > {high_20:.2f}",
                    exit_type="DONCHIAN_BREAK",
                    urgency="NEXT_BAR"
                )

        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _calculate_r_profit(self, position: Position, close: float, atr: float) -> float:
        if not self._is_valid_numeric(atr) or atr <= 0:
            if position.side == "LONG":
                return (close - position.entry_price) / position.entry_price * 100
            else:
                return (position.entry_price - close) / position.entry_price * 100

        if position.side == "LONG":
            return (close - position.entry_price) / atr
        else:
            return (position.entry_price - close) / atr


exit_manager = ExitManager()
