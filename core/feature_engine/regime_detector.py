"""
AUTOBOT Feature Engine - Regime Detector
Detects market regimes (BULL_TREND, BEAR_TREND, RANGE)
"""
import logging
from typing import Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core.state_manager import MarketRegime, VolatilityRegime

logger = logging.getLogger("autobot.feature.regime")


class RegimeTransition:
    """Configuration for regime state transitions"""
    
    # Bull trend requirements
    BULL_ADX_THRESHOLD = 25
    BULL_EMA_CONFIRM_PERIODS = 3
    BULL_EMA_SHORT = 20
    BULL_EMA_LONG = 50
    
    # Bear trend requirements
    BEAR_ADX_THRESHOLD = 25
    BEAR_EMA_CONFIRM_PERIODS = 3
    BEAR_EMA_SHORT = 20
    BEAR_EMA_LONG = 50
    
    # Range requirements
    RANGE_ADX_THRESHOLD = 20
    RANGE_CONFIRM_PERIODS = 5
    
    # Volatility thresholds
    HIGH_VOLATILITY_ATR_PCT = 1.5
    LOW_VOLATILITY_ATR_PCT = 0.5


@dataclass
class RegimeState:
    """Current regime state"""
    regime: MarketRegime = MarketRegime.UNKNOWN
    volatility: VolatilityRegime = VolatilityRegime.NORMAL
    regime_periods: int = 0  # Number of periods in current regime
    last_transition: datetime = None
    
    def __post_init__(self):
        if self.last_transition is None:
            self.last_transition = datetime.utcnow()


class RegimeDetector:
    """Detects market regimes using technical indicators"""
    
    def __init__(self):
        self._state = RegimeState()
        self._ema_short_history: list = []
        self._adx_history: list = []
        self._max_history = 10
    
    def detect(self, features: dict) -> MarketRegime:
        """
        Detect the current market regime.
        
        Args:
            features: Dictionary of indicator values
        
        Returns:
            Current MarketRegime
        """
        
        adx = features.get("adx", 0)
        ema_short = features.get("ema_20", 0)
        ema_long = features.get("ema_50", 0)
        ema_above = ema_short > ema_long
        
        # Update history
        self._ema_short_history.append(ema_above)
        self._adx_history.append(adx)
        
        if len(self._ema_short_history) > self._max_history:
            self._ema_short_history.pop(0)
        if len(self._adx_history) > self._max_history:
            self._adx_history.pop(0)
        
        # Detect regime
        new_regime = self._detect_regime(adx, ema_above)
        
        # Check for regime transition
        if new_regime != self._state.regime:
            self._state.regime = new_regime
            self._state.regime_periods = 0
            self._state.last_transition = datetime.utcnow()
            logger.info(f"Regime transition: {new_regime.value}")
        else:
            self._state.regime_periods += 1
        
        return self._state.regime
    
    def _detect_regime(self, adx: float, ema_above: bool) -> MarketRegime:
        """Determine regime based on indicators"""
        
        # Check for trending conditions
        if len(self._adx_history) >= RegimeTransition.BULL_EMA_CONFIRM_PERIODS:
            recent_adx = all(a > RegimeTransition.BULL_ADX_THRESHOLD for a in self._adx_history[-RegimeTransition.BULL_EMA_CONFIRM_PERIODS:])
            recent_ema = all(self._ema_short_history[-RegimeTransition.BULL_EMA_CONFIRM_PERIODS:])
            
            if recent_adx and recent_ema:
                return MarketRegime.BULL_TREND
            
            recent_ema_bear = all(not e for e in self._ema_short_history[-RegimeTransition.BEAR_EMA_CONFIRM_PERIODS:])
            if recent_adx and recent_ema_bear:
                return MarketRegime.BEAR_TREND
        
        # Check for range conditions
        if len(self._adx_history) >= RegimeTransition.RANGE_CONFIRM_PERIODS:
            recent_low_adx = all(a < RegimeTransition.RANGE_ADX_THRESHOLD for a in self._adx_history[-RegimeTransition.RANGE_CONFIRM_PERIODS:])
            if recent_low_adx:
                return MarketRegime.RANGE
        
        # Default to current regime if no clear signal
        return self._state.regime if self._state.regime != MarketRegime.UNKNOWN else MarketRegime.RANGE
    
    def detect_volatility(self, features: dict) -> VolatilityRegime:
        """Detect volatility regime"""
        
        atr_pct = features.get("atr_pct", 0)
        
        if atr_pct > RegimeTransition.HIGH_VOLATILITY_ATR_PCT:
            self._state.volatility = VolatilityRegime.HIGH
        elif atr_pct < RegimeTransition.LOW_VOLATILITY_ATR_PCT:
            self._state.volatility = VolatilityRegime.LOW
        else:
            self._state.volatility = VolatilityRegime.NORMAL
        
        return self._state.volatility
    
    def get_state(self) -> RegimeState:
        """Get current regime state"""
        return self._state
