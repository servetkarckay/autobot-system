"""
AUTOBOT Position Sizing - Turtle Trading N-Unit System
Risk-based position sizing using ATR

FIXED v1.1:
- Added comprehensive NaN/Infinity protection
- Added division by zero safety checks
- Added input validation with early returns
- Added safe mathematical operations
"""
import logging
import math
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
    Stop loss distance = 2 x ATR
    Position size adjusts inversely with volatility
    """
    
    def __init__(
        self,
        risk_per_trade_pct: float = 100.0,
        atr_multiplier: float = 2.0,
        min_quantity_usdt: float = 1.0,
        max_position_usdt: float = 1000.0
    ):
        if not 0 < risk_per_trade_pct <= 100:
            raise ValueError(f"risk_per_trade_pct must be between 0 and 100, got {risk_per_trade_pct}")
        if not atr_multiplier > 0:
            raise ValueError(f"atr_multiplier must be positive, got {atr_multiplier}")
        if not min_quantity_usdt > 0:
            raise ValueError(f"min_quantity_usdt must be positive, got {min_quantity_usdt}")
        if not max_position_usdt > min_quantity_usdt:
            raise ValueError(f"max_position_usdt must be > min_quantity_usdt")
        
        self.risk_per_trade_pct = risk_per_trade_pct / 100.0
        self.atr_multiplier = atr_multiplier
        self.min_quantity_usdt = min_quantity_usdt
        self.max_position_usdt = max_position_usdt
        
        logger.info(f"PositionSizer initialized: risk={risk_per_trade_pct:.1%}, atr_mult={atr_multiplier}x")
    
    def _safe_divide(self, numerator: float, denominator: float, default: float = 0.0) -> float:
        """Safe division with zero-check and NaN protection"""
        try:
            if denominator == 0 or math.isclose(denominator, 0, abs_tol=1e-10):
                return default
            result = numerator / denominator
            if not math.isfinite(result):
                return default
            return result
        except (ZeroDivisionError, ValueError, OverflowError):
            return default
    
    def _is_valid_numeric(self, value: float, allow_zero: bool = False) -> bool:
        """Check if value is a valid finite number"""
        try:
            return (
                isinstance(value, (int, float)) and
                math.isfinite(value) and
                not math.isnan(value) and
                (allow_zero or value > 0)
            )
        except (TypeError, ValueError):
            return False
    
    def calculate(
        self,
        equity: float,
        price: float,
        atr: float,
        symbol: str = ""
    ) -> PositionSizeResult:
        if not self._is_valid_numeric(equity, allow_zero=False):
            logger.warning(f"[POSITION SIZER] {symbol}: Invalid equity: {equity}")
            return PositionSizeResult(
                quantity=0.0, position_value_usdt=0.0, risk_amount_usdt=0.0,
                stop_distance_pct=0.0, reason="Invalid equity (must be positive finite number)", valid=False
            )
        
        if not self._is_valid_numeric(price, allow_zero=False):
            logger.warning(f"[POSITION SIZER] {symbol}: Invalid price: {price}")
            return PositionSizeResult(
                quantity=0.0, position_value_usdt=0.0, risk_amount_usdt=0.0,
                stop_distance_pct=0.0, reason="Invalid price (must be positive finite number)", valid=False
            )
        
        if not self._is_valid_numeric(atr, allow_zero=True):
            logger.warning(f"[POSITION SIZER] {symbol}: Invalid ATR: {atr}, using fallback")
            atr = 0.0
        
        atr_pct_of_price = self._safe_divide(atr, price, default=0.0)
        MIN_ATR_PCT = 0.005
        
        if atr <= 0 or atr_pct_of_price < MIN_ATR_PCT:
            logger.debug(f"[POSITION SIZER] {symbol}: ATR too small, using {MIN_ATR_PCT:.1%} fallback")
            atr = price * MIN_ATR_PCT
        
        risk_amount = equity * self.risk_per_trade_pct
        
        if not self._is_valid_numeric(risk_amount, allow_zero=True):
            logger.error(f"[POSITION SIZER] {symbol}: Invalid risk_amount: {risk_amount}")
            return PositionSizeResult(
                quantity=0.0, position_value_usdt=0.0, risk_amount_usdt=0.0,
                stop_distance_pct=0.0, reason="Calculation error - invalid risk amount", valid=False
            )
        
        stop_distance = atr * self.atr_multiplier
        
        if not self._is_valid_numeric(stop_distance, allow_zero=False):
            logger.error(f"[POSITION SIZER] {symbol}: Invalid stop_distance: {stop_distance}")
            return PositionSizeResult(
                quantity=0.0, position_value_usdt=0.0, risk_amount_usdt=risk_amount,
                stop_distance_pct=0.0, reason="Calculation error - invalid stop distance", valid=False
            )
        
        position_value = self._safe_divide(risk_amount, stop_distance, default=0.0)
        
        if position_value <= 0:
            logger.error(f"[POSITION SIZER] {symbol}: Invalid position_value: {position_value}")
            return PositionSizeResult(
                quantity=0.0, position_value_usdt=0.0, risk_amount_usdt=risk_amount,
                stop_distance_pct=0.0, reason="Calculation error - invalid position value", valid=False
            )
        
        quantity = self._safe_divide(position_value, price, default=0.0)
        
        if quantity <= 0:
            logger.error(f"[POSITION SIZER] {symbol}: Invalid quantity: {quantity}")
            return PositionSizeResult(
                quantity=0.0, position_value_usdt=0.0, risk_amount_usdt=risk_amount,
                stop_distance_pct=0.0, reason="Calculation error - invalid quantity", valid=False
            )
        
        stop_distance_pct = self._safe_divide(stop_distance, price, default=0.0) * 100
        
        if position_value < self.min_quantity_usdt:
            logger.debug(f"[POSITION SIZER] {symbol}: Value ${position_value:.2f} below minimum ${self.min_quantity_usdt}")
            return PositionSizeResult(
                quantity=0.0, position_value_usdt=position_value, risk_amount_usdt=risk_amount,
                stop_distance_pct=stop_distance_pct, reason=f"Position value ${position_value:.2f} below minimum", valid=False
            )
        
        final_position_value = position_value
        final_quantity = quantity
        
        if position_value > self.max_position_usdt:
            logger.debug(f"[POSITION SIZER] {symbol}: Capping at ${self.max_position_usdt}")
            final_position_value = self.max_position_usdt
            final_quantity = self._safe_divide(final_position_value, price, default=0.0)
            
            if final_quantity <= 0:
                logger.error(f"[POSITION SIZER] {symbol}: Capped quantity invalid: {final_quantity}")
                return PositionSizeResult(
                    quantity=0.0, position_value_usdt=0.0, risk_amount_usdt=risk_amount,
                    stop_distance_pct=stop_distance_pct, reason="Calculation error after capping", valid=False
                )
        
        final_quantity = round(final_quantity, 3)
        
        if not self._is_valid_numeric(final_quantity, allow_zero=False):
            logger.error(f"[POSITION SIZER] {symbol}: Final quantity validation failed: {final_quantity}")
            return PositionSizeResult(
                quantity=0.0, position_value_usdt=0.0, risk_amount_usdt=risk_amount,
                stop_distance_pct=stop_distance_pct, reason="Final validation failed", valid=False
            )
        
        logger.debug(f"[POSITION SIZER] {symbol}: qty={final_quantity:.3f}, value=${final_position_value:.2f}")
        
        return PositionSizeResult(
            quantity=final_quantity,
            position_value_usdt=final_position_value,
            risk_amount_usdt=risk_amount,
            stop_distance_pct=stop_distance_pct,
            reason=f"Calculated: {final_quantity:.3f} @ ${price:.6f}",
            valid=True
        )
    
    def calculate_from_signal(self, equity: float, signal, current_price: float) -> PositionSizeResult:
        atr_val = signal.atr if hasattr(signal, "atr") and self._is_valid_numeric(signal.atr, allow_zero=True) else 0.0
        symbol_val = signal.symbol if hasattr(signal, "symbol") else ""
        return self.calculate(equity=equity, price=current_price, atr=atr_val, symbol=symbol_val)


position_sizer = PositionSizer()
