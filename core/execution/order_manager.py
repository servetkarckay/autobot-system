"""
AUTOBOT Execution Engine - Order Manager
Handles order submission, cancellation, and monitoring
"""
import logging
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import time

from binance import AsyncClient
from binance.exceptions import BinanceAPIException
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
        self._client: Optional[AsyncClient] = None
        self._symbol_filters: Dict[str, Dict] = {}
        self._hedge_mode = None  # Will be detected on first API call
        logger.info(f"OrderManager initialized (dry_run={dry_run})")
    
    async def _get_client(self) -> AsyncClient:
        """Get or create Binance client"""
        if self._client is None:
            api_key = settings.BINANCE_API_KEY.get_secret_value()
            api_secret = settings.BINANCE_API_SECRET.get_secret_value()
            self._client = await AsyncClient.create(
                api_key=api_key,
                api_secret=api_secret,
                testnet=settings.BINANCE_TESTNET
            )
            # Load exchange info for precision rules
            await self._load_symbol_filters()
        return self._client
    
    async def _load_symbol_filters(self):
        """Load trading rules and precision info for all symbols"""
        try:
            info = await self._client.futures_exchange_info()
            for symbol_info in info.get('symbols', []):
                symbol = symbol_info['symbol']
                filters = {f['filterType']: f for f in symbol_info.get('filters', [])}
                self._symbol_filters[symbol] = filters
            logger.info(f"Loaded filters for {len(self._symbol_filters)} symbols")
        except Exception as e:
            logger.warning(f"Failed to load symbol filters: {e}")
    
    def _round_quantity(self, symbol: str, quantity: float) -> str:
        """Round quantity to symbol's precision rules"""
        if symbol not in self._symbol_filters:
            # Default to 3 decimal places
            return f"{quantity:.3f}".rstrip('0').rstrip('.')
        
        lot_size = self._symbol_filters[symbol].get('LOT_SIZE', {})
        if lot_size:
            step_size = float(lot_size.get('stepSize', '0.001'))
            # Calculate precision from step size
            precision = 0
            if step_size < 1:
                precision = len(str(step_size).split('.')[-1].rstrip('0'))
            # Round down to step size
            rounded = int(quantity / step_size) * step_size
            return f"{rounded:.{precision}f}".rstrip('0').rstrip('.')
        
        return f"{quantity:.3f}".rstrip('0').rstrip('.')
    
    def _round_price(self, symbol: str, price: float) -> str:
        """Round price to symbol's precision rules"""
        if symbol not in self._symbol_filters:
            return f"{price:.8f}".rstrip('0').rstrip('.')
        
        price_filter = self._symbol_filters[symbol].get('PRICE_FILTER', {})
        if price_filter:
            tick_size = float(price_filter.get('tickSize', '0.00000001'))
            precision = 0
            if tick_size < 1:
                precision = len(str(tick_size).split('.')[-1].rstrip('0'))
            return f"{price:.{precision}f}".rstrip('0').rstrip('.')
        
        return f"{price:.8f}".rstrip('0').rstrip('.')
    
    async def submit_order(self, signal: TradeSignal, quantity: float, 
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
            return await self._submit_dry_run_order(signal, quantity, price)
        
        # Determine order side and type
        side = "BUY" if "LONG" in signal.action else "SELL"
        position_side = "LONG" if "LONG" in signal.action else "SHORT"
        
        if price is None:
            order_type = "MARKET"
        else:
            order_type = "LIMIT"
        
        try:
            client = await self._get_client()
            
            # Round quantity and price according to symbol rules
            qty_str = self._round_quantity(signal.symbol, quantity)
            
            logger.info(f"Submitting {order_type} order: {signal.symbol} {signal.action} qty={qty_str}")
            
            # Prepare order parameters
            params = {
                "symbol": signal.symbol,
                "side": side,
                "type": order_type,
                "quantity": qty_str,
                "positionSide": position_side  # Required for Hedge Mode
            }
            
            if order_type == "LIMIT" and price is not None:
                price_str = self._round_price(signal.symbol, price)
                params["price"] = price_str
                params["timeInForce"] = "GTC"  # Good Till Cancel
            
            # Submit order to Binance
            result = await client.futures_create_order(**params)
            
            order_id = result.get("orderId", "N/A")
            executed_price = float(result.get("avgPrice", price or 0))
            executed_qty = float(result.get("executedQty", quantity))
            
            logger.info(f"Order FILLED: {signal.symbol} {side} {position_side} ID={order_id} @ {executed_price}")
            
            return OrderResult(
                success=True,
                order_id=str(order_id),
                executed_price=executed_price,
                executed_quantity=executed_qty
            )
            
        except BinanceAPIException as e:
            logger.error(f"Binance API Error: {e.code} - {e.message}")
            return OrderResult(
                success=False,
                error_message=f"API Error {e.code}: {e.message}"
            )
        except Exception as e:
            logger.error(f"Order submission failed: {e}")
            return OrderResult(
                success=False,
                error_message=str(e)
            )
    
    async def _submit_dry_run_order(self, signal: TradeSignal, 
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
    
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an open order"""
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel order: {order_id}")
            return True
        
        try:
            client = await self._get_client()
            await client.futures_cancel_order(symbol=symbol, orderId=int(order_id))
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Order cancellation failed: {e}")
            return False
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> Dict:
        """Get all open orders, optionally filtered by symbol"""
        
        if self.dry_run:
            logger.debug(f"[DRY RUN] Would query open orders for {symbol}")
            return {}
        
        try:
            client = await self._get_client()
            if symbol:
                orders = await client.futures_get_open_orders(symbol=symbol)
            else:
                orders = await client.futures_get_open_orders()
            return {o["orderId"]: o for o in orders}
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return {}
    
    async def close_position(
        self,
        symbol: str,
        position: Position
    ) -> OrderResult:
        """
        Pozisyon kapat (Market order ile)

        Args:
            symbol: Trading sembolü
            position: Kapatılacak pozisyon

        Returns:
            OrderResult
        """

        if self.dry_run:
            logger.info(f"[DRY RUN] Would close position: {symbol} {position.side} qty={position.quantity}")
            return OrderResult(
                success=True,
                order_id=f"DRY_CLOSE_{int(time.time() * 1000)}",
                executed_price=position.current_price,
                executed_quantity=position.quantity
            )

        try:
            client = await self._get_client()

            # Side belirle (LONG için SELL, SHORT için BUY)
            side = "SELL" if position.side == "LONG" else "BUY"

            # Quantity hazırla
            qty_str = self._round_quantity(symbol, position.quantity)

            logger.info(
                f"Closing {position.side} position: {symbol} "
                f"qty={qty_str} type=MARKET"
            )

            # Market order ile kapat
            result = await client.futures_create_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=qty_str,
                positionSide=position.side
            )

            order_id = result.get("orderId", "N/A")
            executed_price = float(result.get("avgPrice", position.current_price))
            executed_qty = float(result.get("executedQty", position.quantity))

            return OrderResult(
                success=True,
                order_id=str(order_id),
                executed_price=executed_price,
                executed_quantity=executed_qty
            )

        except BinanceAPIException as e:
            logger.error(f"Binance API Error closing position: {e.code} - {e.message}")
            return OrderResult(
                success=False,
                error_message=f"API Error {e.code}: {e.message}"
            )
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return OrderResult(
                success=False,
                error_message=str(e)
            )

    async def set_stop_loss(self, position: Position, stop_price: float) -> bool:
        """Set or update stop-loss order for a position"""
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would set stop-loss for {position.symbol} at {stop_price}")
            return True
        
        try:
            client = await self._get_client()
            side = "SELL" if position.side == "LONG" else "BUY"
            position_side = position.side  # LONG or SHORT
            
            await client.futures_create_order(
                symbol=position.symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=self._round_price(position.symbol, stop_price),
                positionSide=position_side,
                closePosition=True
            )
            logger.info(f"Stop-loss set for {position.symbol} at {stop_price}")
            return True
        except Exception as e:
            logger.error(f"Stop-loss setting failed: {e}")
            return False
    
    async def close_all_positions(self) -> int:
        """Close all open positions. Returns number of positions closed"""
        if self.dry_run:
            logger.info("[DRY RUN] Would close all positions")
            return 0
        
        try:
            client = await self._get_client()
            positions = await client.futures_position_information()
            
            closed = 0
            for pos in positions:
                pos_amt = float(pos.get("positionAmt", 0))
                if abs(pos_amt) > 0:
                    symbol = pos["symbol"]
                    position_side = pos.get("positionSide", "BOTH")
                    side = "SELL" if pos_amt > 0 else "BUY"
                    qty = self._round_quantity(symbol, abs(pos_amt))
                    await client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type="MARKET",
                        quantity=qty,
                        positionSide=position_side
                    )
                    closed += 1
                    logger.info(f"Closed position: {symbol} {position_side}")
            
            return closed
        except Exception as e:
            logger.error(f"Failed to close positions: {e}")
            return 0
    
    async def cleanup(self):
        """Clean up resources"""
        if self._client:
            await self._client.close_connection()
            self._client = None


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
