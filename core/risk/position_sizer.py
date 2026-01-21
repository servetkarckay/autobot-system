"""
AUTOBOT Position Sizing - Turtle Trading N-Unit System
Risk-based position sizing using ATR
"""
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger("autobot.risk.position_sizer")


@dataclass
class PositionSizeResult:
    """Result of position sizing calculation"""
    quantity: float
    position_value_usdt: float
    risk_amount_usdt: float
    stop_distance_pct: float
    reason: str = ""
    valid: bool = True


class PositionSizer:
    """
    Turtle Trading N-Unit position sizing system.
    
    Risk per trade = 1% of equity
    Stop loss distance = 2 × ATR
    Position size adjusts inversely with volatility
    """
    
    def __init__(
        self,
        risk_per_trade_pct: float = 1.0,  # %1 of equity
        atr_multiplier: float = 2.0,      # 2N stop loss
        min_quantity_usdt: float = 5.0,     # Minimum trade size
        max_position_usdt: float = 1000.0  # Max per trade
    ):
        self.risk_per_trade_pct = risk_per_trade_pct
        self.atr_multiplier = atr_multiplier
        self.min_quantity_usdt = min_quantity_usdt
        self.max_position_usdt = max_position_usdt
        
        logger.info(f"PositionSizer initialized: risk={risk_per_trade_pct:.1%}, atr_mult={atr_multiplier}x")
    
    def calculate(
        self,
        equity: float,
        price: float,
        atr: float,
        symbol: str = ""
    ) -> PositionSizeResult:
        """
        Calculate position size using Turtle N-unit method.
        
        Formula:
        risk_amount = equity × risk_per_trade_pct
        stop_distance = atr × atr_multiplier
        position_value = risk_amount / stop_distance
        quantity = position_value / price
        
        Args:
            equity: Total account equity
            price: Current price of asset
            atr: Average True Range (volatility measure)
            symbol: Trading pair symbol (for logging)
        
        Returns:
            PositionSizeResult with calculated quantity and metadata
        """
        
        # Validations
        if equity <= 0:
            return PositionSizeResult(
                quantity=0.0,
                position_value_usdt=0.0,
                risk_amount_usdt=0.0,
                stop_distance_pct=0.0,
                reason="Invalid equity",
                valid=False
            )
        
        if price <= 0:
            return PositionSizeResult(
                quantity=0.0,
                position_value_usdt=0.0,
                risk_amount_usdt=0.0,
                stop_distance_pct=0.0,
                reason="Invalid price",
                valid=False
            )
        
        if atr <= 0:
            logger.warning(f"Zero or negative ATR for {symbol}, using default 1% of price")
            atr = price * 0.01  # Fallback: 1% of price as ATR
        
        # Calculate risk amount
        risk_amount = equity * self.risk_per_trade_pct
        
        # Calculate stop distance
        stop_distance = atr * self.atr_multiplier
        
        # Calculate position value (notional exposure)
        position_value = risk_amount / stop_distance
        
        # Calculate quantity
        quantity = position_value / price
        
        # Stop distance as percentage of price
        stop_distance_pct = (stop_distance / price) * 100
        
        # Check minimum
        if position_value < self.min_quantity_usdt:
            return PositionSizeResult(
                quantity=0.0,
                position_value_usdt=0.0,
                risk_amount_usdt=0.0,
                stop_distance_pct=stop_distance_pct,
                reason=f"Position value ({position_value:.2f}) below minimum ({self.min_quantity_usdt})",
                valid=False
            )
        
        # Check maximum
        if position_value > self.max_position_usdt:
            logger.warning(f"Position value ({position_value:.2f}) exceeds maximum ({self.max_position_usdt}), capping")
            position_value = self.max_position_usdt
            quantity = position_value / price
        
        # Round to reasonable precision (3 decimal places for crypto)
        quantity = round(quantity, 3)
        
        logger.debug(
            f"Position sizing {symbol}: equity={equity:.0f}, price={price:.2f}, atr={atr:.4f} -> "
            f"qty={quantity:.3f}, value={position_value:.2f}, risk={risk_amount:.2f}, stop_dist={stop_distance_pct:.2f}%"
        )
        
        return PositionSizeResult(
            quantity=quantity,
            position_value_usdt=position_value,
            risk_amount_usdt=risk_amount,
            stop_distance_pct=stop_distance_pct,
            reason=f"Calculated: {quantity:.3f} contracts @ {price:.2f}",
            valid=True
        )
    
    def calculate_from_signal(
        self,
        equity: float,
        signal,
        current_price: float
    ) -> PositionSizeResult:
        """Calculate position size from TradeSignal"""
        return self.calculate(
            equity=equity,
            price=current_price,
            atr=signal.atr,
            symbol=signal.symbol
        )


# Global instance
position_sizer = PositionSizer()
