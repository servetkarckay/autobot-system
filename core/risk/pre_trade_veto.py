"""
AUTOBOT Risk Brain - Pre-Trade Veto Chain
Implements hierarchical risk controls before order submission
"""
import logging
from typing import Optional
from dataclasses import dataclass

from config.settings import settings
from core.state import TradeSignal, VetoResult, SystemState, Position

logger = logging.getLogger("autobot.risk.pre_trade")


@dataclass
class VetoConfig:
    """Configuration for veto thresholds"""
    max_position_size_usdt: float
    max_positions: int
    correlation_threshold: float
    max_correlation_exposure_pct: float
    max_drawdown_pct: float
    daily_loss_limit_pct: float


class PreTradeVetoChain:
    """Implements the risk veto chain for all trading decisions"""
    
    def __init__(self, config: VetoConfig):
        self.config = config
        self._vetoes = {
            "position_size": self._check_position_size,
            "max_positions": self._check_max_positions,
            "correlation": self._check_correlation,
            "drawdown": self._check_drawdown,
            "daily_loss": self._check_daily_loss,
        }
    
    def evaluate(self, signal: TradeSignal, state: SystemState, 
                 proposed_quantity: float, proposed_price: float) -> VetoResult:
        """
        Evaluate a trading signal through the veto chain.
        
        Args:
            signal: The proposed trading signal
            state: Current system state
            proposed_quantity: Proposed position quantity
            proposed_price: Proposed entry price
        
        Returns:
            VetoResult with approval status and any adjustments
        """
        
        # Check if signal is actionable
        if signal.action in ["NEUTRAL", "CLOSE"]:
            return VetoResult(approved=True)
        
        # Run through veto chain
        for stage, veto_fn in self._vetoes.items():
            result = veto_fn(signal, state, proposed_quantity, proposed_price)
            if not result.approved:
                logger.warning(f"Signal vetoed at stage: {stage}, reason: {result.veto_reason}")
                return result
        
        # All vetoes passed
        logger.info(f"Signal approved: {signal.symbol} {signal.action}")
        return VetoResult(
            approved=True,
            adjusted_quantity=proposed_quantity,
            adjusted_price=proposed_price
        )
    
    def _check_position_size(self, signal: TradeSignal, state: SystemState,
                            quantity: float, price: float) -> VetoResult:

        # Skip check if quantity is None (will be calculated later)
        if quantity is None or quantity <= 0:
            return VetoResult(approved=True)
        
        position_value_usdt = quantity * price
        
        if position_value_usdt > self.config.max_position_size_usdt:
            return VetoResult(
                approved=False,
                veto_reason=f"Position size ${position_value_usdt:.2f} exceeds limit ${self.config.max_position_size_usdt:.2f}",
                veto_stage="position_size"
            )
        
        return VetoResult(approved=True)
    
    def _check_max_positions(self, signal: TradeSignal, state: SystemState,
                            quantity: float, price: float) -> VetoResult:
        """Veto if maximum open positions limit reached"""
        
        # If this is a new position (not adding to existing)
        if signal.symbol not in state.open_positions:
            if len(state.open_positions) >= self.config.max_positions:
                return VetoResult(
                    approved=False,
                    veto_reason=f"Maximum positions ({self.config.max_positions}) already open",
                    veto_stage="max_positions"
                )
        
        return VetoResult(approved=True)
    
    def _check_correlation(self, signal: TradeSignal, state: SystemState,
                          quantity: float, price: float) -> VetoResult:
        """Veto if correlation risk exceeds limit"""
        # Simplified correlation check (would need actual correlation data)
        # For now, just log a warning if opening multiple positions
        if len(state.open_positions) > 0:
            logger.debug(f"Correlation check for {signal.symbol} with {len(state.open_positions)} existing positions")
        
        return VetoResult(approved=True)
    
    def _check_drawdown(self, signal: TradeSignal, state: SystemState,
                       quantity: float, price: float) -> VetoResult:
        """Veto if current drawdown exceeds limit"""
        
        if state.current_drawdown_pct >= self.config.max_drawdown_pct:
            return VetoResult(
                approved=False,
                veto_reason=f"Current drawdown ({state.current_drawdown_pct:.2f}%) exceeds limit ({self.config.max_drawdown_pct}%)",
                veto_stage="drawdown"
            )
        
        return VetoResult(approved=True)
    
    def _check_daily_loss(self, signal: TradeSignal, state: SystemState,
                         quantity: float, price: float) -> VetoResult:
        """Veto if daily loss limit exceeded"""
        
        if state.daily_pnl_pct <= -self.config.daily_loss_limit_pct:
            return VetoResult(
                approved=False,
                veto_reason=f"Daily loss ({state.daily_pnl_pct:.2f}%) exceeds limit (-{self.config.daily_loss_limit_pct}%)",
                veto_stage="daily_loss"
            )
        
        return VetoResult(approved=True)
