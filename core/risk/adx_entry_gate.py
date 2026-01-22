"""
AUTOBOT ADX Entry Gate - Turtle Trading Trend Filter
Filters out choppy/range-bound markets using ADX
FIXED: Removed invalid ADX threshold check since ADX calculation is now validated
"""
import logging
from typing import Dict
from dataclasses import dataclass

from core.state_manager import TradeSignal, VetoResult
from core.execution.exit_manager import exit_manager

logger = logging.getLogger("autobot.risk.adx_gate")


@dataclass
class ADXGateConfig:
    min_adx: float = 25.0
    allow_stable: bool = True
    require_rising: bool = False


class ADXEntryGate:
    """ADX-based entry filter for trend-following systems"""
    
    def __init__(self, config: ADXGateConfig = None):
        self.config = config or ADXGateConfig()
        logger.info(f"[ADX GATE] Initialized: min_adx={self.config.min_adx}")
    
    def check(self, signal: TradeSignal, features: Dict, symbol: str) -> VetoResult:
        """Check if signal passes ADX entry gate"""
        
        if signal.action == "CLOSE":
            return VetoResult(approved=True)
        
        adx = features.get("adx", 0)
        
        # ADX validation is now done in indicators.py
        # We only need to check if it's a valid number
        if adx <= 0 or adx > 100:
            return VetoResult(
                approved=False,
                veto_reason=f"Invalid ADX value: {adx:.1f}. Insufficient data for entry.",
                veto_stage="adx_entry_gate"
            )
        
        adx_trend = exit_manager._get_adx_trend(symbol, adx)
        
        logger.debug(f"[ADX GATE] {symbol}: ADX={adx:.1f}, Trend={adx_trend}")
        
        # Check 1: ADX threshold
        if adx < self.config.min_adx:
            return VetoResult(
                approved=False,
                veto_reason=f"ADX too low: {adx:.1f} < {self.config.min_adx}. Choppy market detected.",
                veto_stage="adx_entry_gate"
            )
        
        # Check 2: ADX must not be FALLING
        if adx_trend == "FALLING":
            return VetoResult(
                approved=False,
                veto_reason=f"ADX is falling ({adx:.1f}), momentum weakening.",
                veto_stage="adx_entry_gate"
            )
        
        logger.info(f"[ADX GATE] {symbol}: PASSED - ADX={adx:.1f}, Trend={adx_trend}")
        return VetoResult(approved=True)


# Global instance
adx_entry_gate = ADXEntryGate()
