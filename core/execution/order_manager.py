"""
AUTOBOT Execution Engine - Order Manager v1.5
Handles order submission, cancellation, and monitoring

FIXES:
- Use cached secret values instead of repeated get_secret_value() calls
- Added better error handling
- Added input validation
- ADDED: Margin check before order submission
- ADDED: Leverage setting via API
- UPDATED: New Algo Order API (2025-12-09+) for STOP/TAKE_PROFIT/TRAILING_STOP
"""
import logging
import asyncio
import math
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import time
import hmac
import hashlib
import aiohttp

from binance import AsyncClient
import websockets
import json
from binance.exceptions import BinanceAPIException
from config.settings import settings
from .rate_limiter import rate_limiter
from core.state_manager import TradeSignal, Position

logger = logging.getLogger("autobot.execution.order")


@dataclass
class OrderResult:
    """Result of an order submission"""
    success: bool
    order_id: Optional[str] = None
    algo_id: Optional[str] = None  # For algo orders
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
        self._stop_orders: Dict[str, str] = {}  # symbol -> algo_id
        self._user_data_stream_key: Optional[str] = None  # Binance listen key
        self._user_data_stream_task: Optional[asyncio.Task] = None  # Listener task
        self._execution_report_callbacks = []  # Callbacks for execution reports
        self._api_key: Optional[str] = None
        self._api_secret: Optional[str] = None
        self._base_url: Optional[str] = None
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

            # Rate limiter: wait before leverage change
            await rate_limiter.wait_if_needed("futures_change_leverage")
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

            self._api_key = api_key
            self._api_secret = api_secret
            self._base_url = settings.BINANCE_BASE_URL

            self._client = AsyncClient(testnet=True, 
                api_key=api_key,
                api_secret=api_secret
            )
            self._client.API_URL = settings.BINANCE_BASE_URL
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

        # Critical: Always use integer rounding for USDT pairs to avoid precision errors
        # Most symbols require whole numbers, fractional quantities often cause API Error -1111
        qty_int = int(quantity)
        if qty_int < 1:
            qty_int = 1
        return str(qty_int)

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
            # Rate limiter: wait before account query
            await rate_limiter.wait_if_needed("futures_account")
            account = await client.futures_account()

            # Get USDT available balance
            available_balance = 0.0
            for asset in account.get("assets", []):
                if asset.get("asset") == "USDT":
                    available_balance = float(asset.get("availableBalance", 0))
                    break

            # Get current positions margin usage
            # Rate limiter: wait before position query
            await rate_limiter.wait_if_needed("futures_position_information")
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
            return False, "API Error - cannot verify margin"

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

            # CRITICAL FIX: Cancel any existing open orders for this symbol before placing new one
            # This prevents accumulation of unfilled LIMIT orders
            try:
                await rate_limiter.wait_if_needed("futures_get_open_orders")
                open_orders = await client.futures_get_open_orders(symbol=signal.symbol)
                if open_orders:
                    logger.warning(f"[CANCEL PREVIOUS ORDERS] {signal.symbol}: Found {len(open_orders)} open orders, canceling...")
                    for order in open_orders:
                        order_id = order.get('orderId')
                        if order_id:
                            await client.futures_cancel_order(symbol=signal.symbol, orderId=order_id)
                            logger.info(f"[CANCEL PREVIOUS ORDERS] {signal.symbol}: Canceled order {order_id}")
                    # Wait a bit for cancellations to process
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"[CANCEL PREVIOUS ORDERS] {signal.symbol}: Error canceling orders: {e}")

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

            # Rate limiter: wait before order submission
            await rate_limiter.wait_if_needed("futures_create_order")
            result = await client.futures_create_order(**params)

            order_id = result.get("orderId", "N/A")
            executed_price = float(result.get("avgPrice", price or 0))
            executed_qty = float(result.get("executedQty", quantity))

            logger.info(f"Order FILLED: {signal.symbol} {side} {position_side} ID={order_id} @ {executed_price}")

            # Auto-place stop loss after successful order fill
            try:
                # Calculate stop loss price (5% from entry for safety)
                if position_side == "LONG":
                    stop_price = executed_price * 0.95  # 5% below entry
                else:  # SHORT
                    stop_price = executed_price * 1.05  # 5% above entry
                
                stop_result = await self.submit_stop_loss_order(
                    symbol=signal.symbol,
                    position_side=position_side,
                    stop_price=stop_price,
                    quantity=executed_qty
                )
                
                if stop_result.success:
                    logger.info(f"[STOP LOSS PLACED] {signal.symbol} {position_side} @ {stop_price}")
                else:
                    logger.warning(f"[STOP LOSS FAILED] {signal.symbol}: {stop_result.error_message}")
                    logger.warning(f"MANUAL STOP LOSS REQUIRED! Position: {signal.symbol} {position_side} {executed_qty} @ {executed_price}")
            except Exception as e:
                logger.error(f"[STOP LOSS ERROR] {signal.symbol}: {e}")
                logger.warning(f"MANUAL STOP LOSS REQUIRED! Position: {signal.symbol} {position_side}")
            
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

    async def confirm_order_on_exchange(self, symbol: str, expected_quantity: float) -> bool:
        """Emirin Binance'da gerçekleştiğini doğrula"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would confirm order for {symbol}")
            return True

        try:
            client = await self._get_client()
            # Rate limiter: wait before position query
            await rate_limiter.wait_if_needed("futures_position_information")
            positions = await client.futures_position_information(symbol=symbol)

            for pos in positions:
                if pos.get('symbol') == symbol:
                    amt = float(pos.get('positionAmt', 0))
                    if abs(amt) > 0.0000001:
                        logger.info(f"[ORDER CONFIRMED] {symbol}: Position confirmed on exchange, amount={amt}")
                        return True

            logger.warning(f"[ORDER NOT FOUND] {symbol}: Order executed but position not found on exchange")
            return False

        except Exception as e:
            logger.error(f"[ORDER CONFIRM ERROR] {symbol}: {e}")
            return False

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel a regular order"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel order {order_id} for {symbol}")
            return True

        try:
            client = await self._get_client()
            await client.futures_cancel_order(symbol=symbol, orderId=int(order_id))
            logger.info(f"[CANCEL] Order {order_id} canceled for {symbol}")
            return True
        except Exception as e:
            logger.error(f"[CANCEL FAILED] {symbol}: {e}")
            return False

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
            # Rate limiter: wait before position query
            await rate_limiter.wait_if_needed("futures_position_information")
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

    # ==================== ALGO ORDER API (NEW 2025-12-09+) ====================

    async def _submit_algo_order(self, params: dict) -> dict:
        """Submit an algo order using the new API endpoint"""
        await self._get_client()

        timestamp = int(time.time() * 1000)
        params['timestamp'] = timestamp

        # Build query string
        query = '&'.join(f'{k}={v}' for k, v in params.items())

        # Create signature
        signature = hmac.new(
            self._api_secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

        url = f'{self._base_url}/fapi/v1/algoOrder?{query}&signature={signature}'
        headers = {'X-MBX-APIKEY': self._api_key}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, timeout=30) as response:
                result = await response.json()
                if response.status != 200:
                    logger.error(f"[ALGO ORDER] Failed: {result}")
                    raise Exception(f"Algo order failed: {result.get('msg', result)}")
                return result

    async def _cancel_algo_order(self, symbol: str, algo_id: str) -> bool:
        """Cancel an algo order using the new API endpoint"""
        await self._get_client()

        timestamp = int(time.time() * 1000)
        params = {
            'symbol': symbol,
            'algoId': algo_id,
            'timestamp': timestamp
        }

        query = '&'.join(f'{k}={v}' for k, v in params.items())
        signature = hmac.new(
            self._api_secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

        url = f'{self._base_url}/fapi/v1/algoOrder?{query}&signature={signature}'
        headers = {'X-MBX-APIKEY': self._api_key}

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers, timeout=30) as response:
                result = await response.json()
                if response.status != 200:
                    logger.warning(f"[ALGO CANCEL] Failed: {result}")
                    return False
                return True

    async def _get_open_algo_orders(self, symbol: str) -> list:
        """Get open algo orders for a symbol"""
        await self._get_client()

        timestamp = int(time.time() * 1000)
        query = f'symbol={symbol}&timestamp={timestamp}'
        signature = hmac.new(
            self._api_secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

        url = f'{self._base_url}/fapi/v1/openAlgoOrders?{query}&signature={signature}'
        headers = {'X-MBX-APIKEY': self._api_key}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=30) as response:
                if response.status != 200:
                    logger.warning(f"[ALGO ORDERS] Failed to fetch: {await response.text()}")
                    return []
                return await response.json()

    async def submit_stop_loss_order(self, symbol: str, position_side: str,
                                     stop_price: float, quantity: float) -> OrderResult:
        """Submit a STOP_MARKET order using the new Algo Order API"""
        if self.dry_run:
            logger.info(f'[DRY RUN] Would submit stop loss: {symbol} {position_side} stop={stop_price:.4f} qty={quantity}')
            return OrderResult(
                success=True,
                order_id=f'DRY_STOP_{int(time.time()*1000)}',
                algo_id=f'DRY_ALGO_{int(time.time()*1000)}',
                executed_price=stop_price
            )

        try:
            stop_price_str = self._round_price(symbol, stop_price)
            qty_str = self._round_quantity(symbol, quantity)

            params = {
                'algoType': 'CONDITIONAL',
                'symbol': symbol,
                'side': 'SELL' if position_side == 'LONG' else 'BUY',
                'type': 'STOP_MARKET',
                'quantity': qty_str,
                'triggerPrice': stop_price_str,  # NEW: triggerPrice instead of stopPrice
                'positionSide': position_side,
                'workingType': 'CONTRACT_PRICE',
            }

            result = await self._submit_algo_order(params)

            algo_id = str(result.get('algoId', 'N/A'))
            self._stop_orders[symbol] = algo_id
            logger.info(f'[STOP ORDER PLACED] {symbol} {position_side} stop={stop_price:.4f} AlgoId={algo_id}')

            return OrderResult(
                success=True,
                order_id=algo_id,
                algo_id=algo_id,
                executed_price=stop_price
            )

        except Exception as e:
            logger.error(f'[STOP ORDER FAILED] {symbol}: {e}')
            return OrderResult(success=False, error_message=str(e))

    async def submit_take_profit_order(self, symbol: str, position_side: str,
                                       tp_price: float, quantity: float) -> OrderResult:
        """Submit a TAKE_PROFIT_MARKET order using the new Algo Order API"""
        if self.dry_run:
            logger.info(f'[DRY RUN] Would submit take profit: {symbol} {position_side} tp={tp_price:.4f} qty={quantity}')
            return OrderResult(
                success=True,
                order_id=f'DRY_TP_{int(time.time()*1000)}',
                algo_id=f'DRY_ALGO_{int(time.time()*1000)}',
                executed_price=tp_price
            )

        try:
            tp_price_str = self._round_price(symbol, tp_price)
            qty_str = self._round_quantity(symbol, quantity)

            params = {
                'algoType': 'CONDITIONAL',
                'symbol': symbol,
                'side': 'SELL' if position_side == 'LONG' else 'BUY',
                'type': 'TAKE_PROFIT_MARKET',
                'quantity': qty_str,
                'triggerPrice': tp_price_str,
                'positionSide': position_side,
                'workingType': 'CONTRACT_PRICE',
            }

            result = await self._submit_algo_order(params)

            algo_id = str(result.get('algoId', 'N/A'))
            logger.info(f'[TAKE PROFIT ORDER PLACED] {symbol} {position_side} tp={tp_price:.4f} AlgoId={algo_id}')

            return OrderResult(
                success=True,
                order_id=algo_id,
                algo_id=algo_id,
                executed_price=tp_price
            )

        except Exception as e:
            logger.error(f'[TAKE PROFIT ORDER FAILED] {symbol}: {e}')
            return OrderResult(success=False, error_message=str(e))

    async def submit_trailing_stop_order(self, symbol: str, position_side: str,
                                         activate_price: float, callback_rate: float,
                                         quantity: float) -> OrderResult:
        """Submit a TRAILING_STOP_MARKET order using the new Algo Order API"""
        if self.dry_run:
            logger.info(f'[DRY RUN] Would submit trailing stop: {symbol} {position_side} activate={activate_price:.4f} callback={callback_rate}% qty={quantity}')
            return OrderResult(
                success=True,
                order_id=f'DRY_TRAIL_{int(time.time()*1000)}',
                algo_id=f'DRY_ALGO_{int(time.time()*1000)}',
                executed_price=activate_price
            )

        try:
            activate_price_str = self._round_price(symbol, activate_price)
            qty_str = self._round_quantity(symbol, quantity)

            params = {
                'algoType': 'CONDITIONAL',
                'symbol': symbol,
                'side': 'SELL' if position_side == 'LONG' else 'BUY',
                'type': 'TRAILING_STOP_MARKET',
                'quantity': qty_str,
                'activatePrice': activate_price_str,
                'callbackRate': str(callback_rate),
                'positionSide': position_side,
                'workingType': 'CONTRACT_PRICE',
            }

            result = await self._submit_algo_order(params)

            algo_id = str(result.get('algoId', 'N/A'))
            logger.info(f'[TRAILING STOP ORDER PLACED] {symbol} {position_side} activate={activate_price:.4f} callback={callback_rate}% AlgoId={algo_id}')

            return OrderResult(
                success=True,
                order_id=algo_id,
                algo_id=algo_id,
                executed_price=activate_price
            )

        except Exception as e:
            logger.error(f'[TRAILING STOP ORDER FAILED] {symbol}: {e}')
            return OrderResult(success=False, error_message=str(e))

    async def update_stop_loss(self, symbol: str, position_side: str,
                              new_stop_price: float, quantity: float) -> bool:
        """Update stop loss by canceling old and placing new"""
        logger.info(f'[UPDATE STOP] {symbol}: {position_side} new_stop={new_stop_price:.4f}')

        old_algo_id = self._stop_orders.get(symbol)
        if old_algo_id:
            cancel_success = await self._cancel_algo_order(symbol, old_algo_id)
            if cancel_success:
                logger.info(f'[UPDATE STOP] {symbol}: Old stop {old_algo_id} canceled')
            if symbol in self._stop_orders:
                del self._stop_orders[symbol]

        result = await self.submit_stop_loss_order(symbol, position_side, new_stop_price, quantity)
        return result.success

    async def close_position(self, symbol: str, position) -> OrderResult:
        """Close an existing position"""
        # First cancel any associated algo orders
        algo_id = self._stop_orders.get(symbol)
        if algo_id:
            await self._cancel_algo_order(symbol, algo_id)
            if symbol in self._stop_orders:
                del self._stop_orders[symbol]

        if self.dry_run:
            logger.info(f'[DRY RUN] Would close position for {symbol}')
            return OrderResult(success=True, order_id=f'DRY_CLOSE_{int(time.time()*1000)}')

        try:
            client = await self._get_client()
            close_side = 'SELL' if position.side == 'LONG' else 'BUY'

            # Rate limiter: wait before order submission
            await rate_limiter.wait_if_needed("futures_create_order")
            result = await client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='MARKET',
                quantity=position.quantity,
                positionSide=position.side
            )

            order_id = result.get('orderId', 'N/A')
            executed_price = float(result.get('avgPrice', position.current_price))

            logger.info(f'[CLOSE FILLED] {symbol} {position.side} ID={order_id} @ {executed_price}')

            return OrderResult(
                success=True,
                order_id=str(order_id),
                executed_price=executed_price,
                executed_quantity=position.quantity
            )

        except Exception as e:
            logger.error(f'[CLOSE FAILED] {symbol}: {e}')
            return OrderResult(success=False, error_message=str(e))

    # ==================== USER DATA STREAM ====================

    async def start_user_data_stream(self) -> bool:
        """Binance User Data Stream'i başlat - Real-time order updates"""
        if self.dry_run:
            logger.info("[DRY RUN] Would start User Data Stream")
            return True

        try:
            client = await self._get_client()
            response = await client.futures_stream_get_listen_key()
            self._user_data_stream_key = response
            logger.info(f"[USER DATA STREAM] Listen key obtained: {self._user_data_stream_key[:20]}...")

            # Start listener task
            self._user_data_stream_task = asyncio.create_task(self._user_data_stream_listener())
            # Start keep-alive task
            asyncio.create_task(self.keep_alive_listen_key())
            logger.info("[USER DATA STREAM] Listener task started")
            return True

        except BinanceAPIException as e:
            logger.error(f"[USER DATA STREAM] Failed to get listen key: {e.code} - {e.message}")
            return False
        except Exception as e:
            logger.error(f"[USER DATA STREAM] Error: {e}")
            return False

    async def stop_user_data_stream(self):
        """User Data Stream'i durdur"""
        if self._user_data_stream_task:
            self._user_data_stream_task.cancel()
            try:
                await self._user_data_stream_task
            except asyncio.CancelledError:
                pass

        if self._user_data_stream_key and self._client:
            try:
                await self._client.futures_stream_close_listen_key(listenKey=self._user_data_stream_key)
                logger.info("[USER DATA STREAM] Listen key closed")
            except Exception as e:
                logger.warning(f"[USER DATA STREAM] Failed to close listen key: {e}")

    async def _user_data_stream_listener(self):
        """Binance User Data Stream'den execution report dinle"""
        uri = f"wss://fstream.binance.com/ws/{self._user_data_stream_key}"

        while True:
            try:
                async with websockets.connect(uri) as ws:
                    logger.info("[USER DATA STREAM] Connected to Binance User Data Stream")

                    while True:
                        message = await ws.recv()
                        data = json.loads(message)

                        # Execution event'ini işle
                        if data.get('e') == 'ORDER_TRADE_UPDATE':
                            await self._handle_execution_report(data.get('o', {}))

                        # Account update
                        elif data.get('e') == 'ACCOUNT_UPDATE':
                            await self._handle_account_update(data.get('a', {}))

                        # Listen key expired (24 hours)
                        elif data.get('e') == 'listenKeyExpired':
                            logger.warning("[USER DATA STREAM] Listen key expired, refreshing...")
                            await self.stop_user_data_stream()
                            await self.start_user_data_stream()

            except websockets.exceptions.ConnectionClosed:
                logger.warning("[USER DATA STREAM] Connection closed, reconnecting...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[USER DATA STREAM] Error: {e}")
                await asyncio.sleep(10)

    async def _handle_execution_report(self, order_data: dict):
        """Execution report'ini işle ve local state'i güncelle"""
        order_id = str(order_data.get('i'))
        symbol = order_data.get('s')
        order_status = order_data.get('X')
        execution_type = order_data.get('x')

        logger.debug(f"[EXECUTION REPORT] {symbol} Order {order_id}: Status={order_status}, ExecType={execution_type}")

        # Sadece önemli durumları işle
        if order_status in ['FILLED', 'PARTIALLY_FILLED', 'CANCELED', 'REJECTED', 'EXPIRED']:
            # Callback'leri çağır
            for callback in self._execution_report_callbacks:
                try:
                    await callback(order_data)
                except Exception as e:
                    logger.error(f"[EXECUTION REPORT] Callback error: {e}")

        # Filled emir için log
        if execution_type == 'TRADE':
            executed_qty = float(order_data.get('l', 0))
            executed_price = float(order_data.get('L', 0))
            logger.info(f"[ORDER FILLED] {symbol} {order_id}: {executed_qty} @ {executed_price}")

    async def _handle_account_update(self, account_data: dict):
        """Account update'ini işle"""
        positions = account_data.get('P', [])
        for pos in positions:
            symbol = pos.get('s')
            position_amt = float(pos.get('pa', 0))
            unrealized_pnl = float(pos.get('up', 0)) if 'up' in pos else 0

            if abs(position_amt) > 0:
                logger.debug(f"[ACCOUNT UPDATE] {symbol}: {position_amt} contracts, PnL: {unrealized_pnl}")

    def on_execution_report(self, callback):
        """Execution report için callback ekle"""
        self._execution_report_callbacks.append(callback)

    async def keep_alive_listen_key(self):
        """Listen key'i canlı tut (her 30 dakikada bir ping)"""
        while True:
            try:
                await asyncio.sleep(1800)  # 30 dakika
                if self._user_data_stream_key and self._client:
                    await self._client.futures_stream_keepalive(listenKey=self._user_data_stream_key)
                    logger.debug("[USER DATA STREAM] Listen key kept alive")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[USER DATA STREAM] Keep-alive error: {e}")
