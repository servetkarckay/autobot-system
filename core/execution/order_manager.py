"""
AUTOBOT Execution Engine - Order Manager
Handles order submission, cancellation, and monitoring
"""
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import time

from config.settings import settings
from core.state import TradeSignal, Position

logger = logging.getLogger("autobot.execution.order")


@dataclass
class OrderResult:
    """Result of an order submission"""
    success: bool
    order_id: Optional[str] = None
    error_message: Optional[str] = None
    executed_price: Optional[float] = None
    executed_quantity: Optional[float] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class OrderManager:
    """Manages order lifecycle for trading execution"""
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._open_orders: Dict[str, Dict] = {}
        logger.info(f"OrderManager initialized (dry_run={dry_run})")
    
    def submit_order(self, signal: TradeSignal, quantity: float, 
                    price: Optional[float] = None) -> OrderResult:
        """
        Submit an order based on a trading signal.
        
        Args:
            signal: The approved trading signal
            quantity: Order quantity in base asset
            price: Limit price (None for market orders)
        
        Returns:
            OrderResult with execution details
        """
        
        if self.dry_run:
            return self._submit_dry_run_order(signal, quantity, price)
        
        # Determine order type
        if price is None:
            order_type = "MARKET"
        else:
            order_type = "LIMIT"
        
        try:
            # Here you would integrate with Binance API
            # For now, simulate the order
            logger.info(f"Submitting {order_type} order: {signal.symbol} {signal.action} qty={quantity}")
            
            # Simulated order ID
            order_id = f"DRY_{int(time.time() * 1000)}"
            
            return OrderResult(
                success=True,
                order_id=order_id,
                executed_price=price or 0.0,
                executed_quantity=quantity
            )
            
        except Exception as e:
            logger.error(f"Order submission failed: {e}")
            return OrderResult(
                success=False,
                error_message=str(e)
            )
    
    def _submit_dry_run_order(self, signal: TradeSignal, 
                             quantity: float, price: Optional[float]) -> OrderResult:
        """Simulate order submission in dry-run mode"""
        
        logger.info(f"[DRY RUN] Would submit order: {signal.symbol} {signal.action} "
                   f"qty={quantity} price={price}")
        
        return OrderResult(
            success=True,
            order_id=f"DRY_{int(time.time() * 1000)}",
            executed_price=price or 0.0,
            executed_quantity=quantity
        )
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an open order"""
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel order: {order_id}")
            return True
        
        try:
            # Here you would call Binance API to cancel
            logger.info(f"Cancelling order: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Order cancellation failed: {e}")
            return False
    
    def get_open_orders(self, symbol: Optional[str] = None) -> Dict:
        """Get all open orders, optionally filtered by symbol"""
        
        if self.dry_run:
            logger.debug(f"[DRY RUN] Would query open orders for {symbol}")
            return {}
        
        # Here you would query Binance API
        return self._open_orders
    
    def set_stop_loss(self, position: Position, stop_price: float) -> bool:
        """Set or update stop-loss order for a position"""
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would set stop-loss for {position.symbol} at {stop_price}")
            return True
        
        try:
            # Here you would submit stop-loss order via Binance API
            logger.info(f"Setting stop-loss for {position.symbol} at {stop_price}")
            return True
        except Exception as e:
            logger.error(f"Stop-loss setting failed: {e}")
            return False


class SlippageController:
    """Monitors and controls for excessive slippage"""
    
    def __init__(self, max_slippage_pct: float = 0.1):
        self.max_slippage_pct = max_slippage_pct
    
    def check_slippage(self, expected_price: float, 
                      executed_price: float, side: str) -> bool:
        """
        Check if slippage is within acceptable limits.
        
        Args:
            expected_price: The expected fill price
            executed_price: The actual fill price
            side: "LONG" or "SHORT"
        
        Returns:
            True if slippage is acceptable, False otherwise
        """
        
        if side == "LONG":
            slippage_pct = ((executed_price - expected_price) / expected_price) * 100
        else:  # SHORT
            slippage_pct = ((expected_price - executed_price) / expected_price) * 100
        
        acceptable = slippage_pct <= self.max_slippage_pct
        
        if not acceptable:
            logger.warning(f"Excessive slippage detected: {slippage_pct:.2f}% "
                         f"(max: {self.max_slippage_pct}%)")
        else:
            logger.debug(f"Slippage acceptable: {slippage_pct:.2f}%")
        
        return acceptable
