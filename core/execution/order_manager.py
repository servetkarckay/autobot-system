"""
AUTOBOT Execution Engine - Order Manager v1.4
Handles order submission, cancellation, and monitoring

FIXES:
- Use cached secret values instead of repeated get_secret_value() calls
- Added better error handling
- Added input validation
- ADDED: Margin check before order submission
- ADDED: Leverage setting via API
"""
import logging
import asyncio
import math
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import time

from binance import AsyncClient
from binance.exceptions import BinanceAPIException
from config.settings import settings
from core.state_manager import TradeSignal, Position

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
        self._hedge_mode = None
        self._leverage_set: Dict[str, bool] = {}
        logger.info(f"OrderManager initialized (dry_run={dry_run}, leverage={settings.LEVERAGE}x)")

    async def set_leverage(self, symbol: str) -> bool:
        """Set leverage for symbol on Binance Futures"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would set leverage for {symbol} to {settings.LEVERAGE}x")
            return True
        
        if symbol in self._leverage_set:
            return True
        
        try:
            client = await self._get_client()
            leverage = settings.LEVERAGE
            
            result = await client.futures_change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            
            self._leverage_set[symbol] = True
            logger.info(f"[LEVERAGE] {symbol}: Set to {leverage}x on Binance")
            return True
            
        except BinanceAPIException as e:
            logger.error(f"[LEVERAGE] Failed to set leverage for {symbol}: {e.code} - {e.message}")
            return False
        except Exception as e:
            logger.error(f"[LEVERAGE] Error setting leverage for {symbol}: {e}")
            return False

    def _is_valid_numeric(self, value: float) -> bool:
        """Check if value is valid finite number"""
        return isinstance(value, (int, float)) and math.isfinite(value) and not math.isnan(value) and value > 0

    async def _get_client(self) -> AsyncClient:
        """Get or create Binance client using cached credentials"""
        if self._client is None:
            api_key = settings.binance_api_key
            api_secret = settings.binance_api_secret

            if not api_key or not api_secret:
                raise ValueError("Binance API credentials not configured")

            self._client = await AsyncClient.create(
                api_key=api_key,
                api_secret=api_secret,
                testnet=settings.BINANCE_TESTNET
            )
            await self._load_symbol_filters()
        return self._client

    async def _load_symbol_filters(self):
        """Load trading rules and precision info for all symbols"""
        try:
            info = await self._client.futures_exchange_info()
            for symbol_info in info.get("symbols", []):
                symbol = symbol_info["symbol"]
                filters = {f["filterType"]: f for f in symbol_info.get("filters", [])}
                self._symbol_filters[symbol] = filters
            logger.info(f"Loaded filters for {len(self._symbol_filters)} symbols")
        except Exception as e:
            logger.warning(f"Failed to load symbol filters: {e}")

    def _round_quantity(self, symbol: str, quantity: float) -> str:
        """Round quantity to symbol's precision rules"""
        if not self._is_valid_numeric(quantity):
            logger.warning(f"Invalid quantity for rounding: {quantity}")
            return "0.001"

        if symbol not in self._symbol_filters:
            return f"{quantity:.3f}".rstrip("0").rstrip(".")

        lot_size = self._symbol_filters[symbol].get("LOT_SIZE", {})
        if lot_size:
            step_size = float(lot_size.get("stepSize", "0.001"))
            precision = 0
            if step_size < 1:
                precision = len(str(step_size).split(".")[-1].rstrip("0"))
            rounded = int(quantity / step_size) * step_size
            return f"{rounded:.{precision}f}".rstrip("0").rstrip(".")

        return f"{quantity:.3f}".rstrip("0").rstrip(".")

    def _round_price(self, symbol: str, price: float) -> str:
        """Round price to symbol's precision rules"""
        if not self._is_valid_numeric(price):
            logger.warning(f"Invalid price for rounding: {price}")
            return f"{price:.8f}".rstrip("0").rstrip(".")

        if symbol not in self._symbol_filters:
            return f"{price:.8f}".rstrip("0").rstrip(".")

        price_filter = self._symbol_filters[symbol].get("PRICE_FILTER", {})
        if price_filter:
            tick_size = float(price_filter.get("tickSize", "0.00000001"))
            precision = 0
            if tick_size < 1:
                precision = len(str(tick_size).split(".")[-1].rstrip("0"))
            return f"{price:.{precision}f}".rstrip("0").rstrip(".")

        return f"{price:.8f}".rstrip("0").rstrip(".")

    async def _check_margin_sufficient(self, symbol: str, position_value_usdt: float) -> tuple[bool, str]:
        """Check if sufficient margin is available before opening position"""
        try:
            client = await self._get_client()
            account = await client.get_account()

            # Get USDT available balance
            available_balance = 0.0
            for asset in account.get("assets", []):
                if asset.get("asset") == "USDT":
                    available_balance = float(asset.get("availableBalance", 0))
                    break

            # Get current positions margin usage
            positions = await client.futures_position_information(symbol=symbol)
            current_position_margin = 0.0
            leverage = settings.LEVERAGE
            for pos in positions:
                if pos.get("symbol") == symbol and pos.get("positionSide") in ["LONG", "SHORT"]:
                    current_position_margin = abs(float(pos.get("notional", 0))) / leverage

            # Required margin with configured leverage
            required_margin = position_value_usdt / leverage
            available_for_trade = available_balance - current_position_margin

            logger.debug(f"[MARGIN CHECK] {symbol}: Balance=${available_balance:.2f}, PositionMargin=${current_position_margin:.2f}, Required={required_margin:.2f}, Available={available_for_trade:.2f}, Leverage={leverage}x")

            if available_for_trade < required_margin:
                return False, f"Insufficient margin: need ${required_margin:.2f}, have ${available_for_trade:.2f}"

            return True, f"Margin OK: ${available_for_trade:.2f} available ({leverage}x leverage)"

        except Exception as e:
            logger.error(f"[MARGIN CHECK] Error: {e}")
            return True, "Margin check skipped (API error)"

    async def submit_order(self, signal: TradeSignal, quantity: float,
                    price: Optional[float] = None) -> OrderResult:
        """Submit an order based on a trading signal"""
        
        # Set leverage first
        await self.set_leverage(signal.symbol)
        
        # Check margin before submitting order
        position_value = quantity * (price or 100.0)
        margin_ok, margin_msg = await self._check_margin_sufficient(signal.symbol, position_value)

        if not margin_ok:
            logger.warning(f"[MARGIN CHECK FAILED] {signal.symbol}: {margin_msg}")
            return OrderResult(
                success=False,
                error_message=f"Insufficient margin: {margin_msg}"
            )

        logger.info(f"[MARGIN CHECK] {signal.symbol}: {margin_msg}")

        if not self._is_valid_numeric(quantity):
            return OrderResult(
                success=False,
                error_message=f"Invalid quantity: {quantity}"
            )

        if self.dry_run:
            return await self._submit_dry_run_order(signal, quantity, price)

        side = "BUY" if "LONG" in signal.action else "SELL"
        position_side = "LONG" if "LONG" in signal.action else "SHORT"
        order_type = "MARKET" if price is None else "LIMIT"

        try:
            client = await self._get_client()
            qty_str = self._round_quantity(signal.symbol, quantity)

            logger.info(f"Submitting {order_type} order: {signal.symbol} {signal.action} qty={qty_str}")

            params = {
                "symbol": signal.symbol,
                "side": side,
                "type": order_type,
                "quantity": qty_str,
                "positionSide": position_side
            }

            if order_type == "LIMIT" and price is not None:
                price_str = self._round_price(signal.symbol, price)
                params["price"] = price_str
                params["timeInForce"] = "GTC"

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


    async def get_open_positions(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch current open positions from exchange for given symbols.
        
        Args:
            symbols: List of symbols to fetch positions for
            
        Returns:
            Dictionary mapping symbol to position data dict.
        """
        if self.dry_run:
            logger.debug(f"[DRY RUN] get_open_positions: Would fetch positions for {symbols}")
            return {}
        
        try:
            client = await self._get_client()
            positions = await client.futures_position_information()
            
            result = {}
            for pos in positions:
                symbol = pos.get("symbol", "")
                if symbol not in symbols:
                    continue
                
                position_amt = float(pos.get("positionAmt", 0))
                if abs(position_amt) < 0.00000001:
                    continue
                
                result[symbol] = {
                    "positionAmt": position_amt,
                    "entryPrice": float(pos.get("entryPrice", 0)),
                    "markPrice": float(pos.get("markPrice", 0)),
                    "unrealizedPnl": float(pos.get("unRealizedProfit", 0)),
                    "updateTime": pos.get("updateTime", 0),
                }
                logger.debug(f"[POSITIONS] {symbol}: {position_amt}")
            
            logger.info(f"[POSITIONS] Found {len(result)} open positions")
            return result
            
        except Exception as e:
            logger.error(f"[POSITIONS] Error: {e}")
            return {}
