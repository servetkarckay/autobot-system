"""
AUTOBOT Data Pipeline - WebSocket Collector (Multi-Connection)
Real-time market data collection from Binance WebSocket
Supports multiple connections for large symbol lists
Fixed: Improved ping/timeout settings for high-symbol count
"""
import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Dict, Any, Set, List
from enum import Enum

try:
    import websockets
except ImportError:
    websockets = None

from config.settings import settings
from core.notifier import notification_manager, NotificationPriority

logger = logging.getLogger("autobot.data.websocket")


class StreamType(Enum):
    KLINE = "kline"
    AGG_TRADE = "aggTrade"
    BOOK_TICKER = "bookTicker"
    DEPTH = "depth"


@dataclass
class MarketData:
    """Normalized market data structure"""
    symbol: str
    stream_type: StreamType
    timestamp: datetime
    received_at: datetime
    latency_ms: float
    
    # Kline specific
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    is_kline_closed: bool = False
    
    # Trade specific
    trade_id: Optional[int] = None
    trade_price: Optional[float] = None
    trade_qty: Optional[float] = None
    
    # Book ticker specific
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    bid_qty: Optional[float] = None
    ask_qty: Optional[float] = None


@dataclass
class LatencyMetrics:
    """Latency tracking metrics"""
    samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    current_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    def update(self, latency_ms: float):
        self.samples.append(latency_ms)
        self.current_latency_ms = latency_ms
        
        if len(self.samples) > 0:
            samples_list = list(self.samples)
            self.avg_latency_ms = sum(samples_list) / len(samples_list)
            self.max_latency_ms = max(samples_list)
            
            sorted_samples = sorted(samples_list)
            self.p95_latency_ms = sorted_samples[int(len(sorted_samples) * 0.95)]
            self.p99_latency_ms = sorted_samples[int(len(sorted_samples) * 0.99)]


class SingleWebSocketConnection:
    """Manages a single WebSocket connection for a batch of symbols"""
    
    # Enhanced timeout settings for high-volume symbol lists
    PING_INTERVAL = 30       # Send ping every 30 seconds
    PING_TIMEOUT = 20        # Wait 20 seconds for pong response
    CLOSE_TIMEOUT = 20       # Wait 20 seconds for close handshake
    MAX_QUEUE_SIZE = 2**16   # Larger message queue for high throughput
    
    def __init__(self, symbols: List[str], connection_id: int, base_url: str,
                 on_message_callback: Callable, on_error_callback: Callable = None):
        self.symbols = symbols
        self.connection_id = connection_id
        self.base_url = base_url
        self._on_message_callback = on_message_callback
        self._on_error_callback = on_error_callback
        
        self._ws = None
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = settings.WEBSOCKET_MAX_RECONNECT_ATTEMPTS
        self._reconnect_delay = settings.WEBSOCKET_RECONNECT_DELAY
        
        self._subscriptions: Set[str] = set()
        self._task = None
        self._should_stop = False
        
        logger.debug(f"Created WebSocket connection #{connection_id} for {len(symbols)} symbols")
    
    def subscribe_klines(self, symbols: list, interval: str = "1m"):
        """Subscribe to kline stream for symbols"""
        for symbol in symbols:
            stream = f"{symbol.lower()}@kline_{interval}"
            self._subscriptions.add(stream)
        logger.debug(f"Connection #{self.connection_id}: Subscribed to {len(symbols)} klines")
    
    def subscribe_book_ticker(self, symbols: list):
        """Subscribe to book ticker stream for symbols"""
        for symbol in symbols:
            stream = f"{symbol.lower()}@bookTicker"
            self._subscriptions.add(stream)
        logger.debug(f"Connection #{self.connection_id}: Subscribed to {len(symbols)} book tickers")
    
    async def start(self):
        """Start this WebSocket connection"""
        self._should_stop = False
        self._task = asyncio.create_task(self._run_connection())
        logger.info(f"Connection #{self.connection_id}: Starting...")
    
    async def stop(self):
        """Stop this WebSocket connection"""
        self._should_stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Connection #{self.connection_id}: Stopped")
    
    async def _run_connection(self):
        """Run the WebSocket connection with auto-reconnect"""
        
        while self._reconnect_attempts < self._max_reconnect_attempts and not self._should_stop:
            try:
                await self._connect()
                return  # Connected successfully, exit reconnect loop
            except asyncio.CancelledError:
                logger.info(f"Connection #{self.connection_id}: Task cancelled")
                raise
            except Exception as e:
                self._reconnect_attempts += 1
                logger.warning(f"Connection #{self.connection_id}: Failed (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts}): {e}")
                
                if self._on_error_callback:
                    try:
                        await self._on_error_callback(e)
                    except Exception as cb_error:
                        logger.error(f"Error callback failed: {cb_error}")
                
                if self._reconnect_attempts < self._max_reconnect_attempts and not self._should_stop:
                    # Exponential backoff for reconnection
                    backoff_delay = min(self._reconnect_delay * (1.5 ** (self._reconnect_attempts - 1)), 60)
                    logger.info(f"Connection #{self.connection_id}: Reconnecting in {backoff_delay:.1f}s...")
                    await asyncio.sleep(backoff_delay)
        
        if not self._should_stop:
            logger.error(f"Connection #{self.connection_id}: Failed after {self._max_reconnect_attempts} attempts")
    
    async def _connect(self):
        """Establish WebSocket connection"""
        
        # Build streams URL
        if len(self._subscriptions) > 0:
            streams = "/".join(self._subscriptions)
            url = f"{self.base_url}/{streams}"
        else:
            url = self.base_url
        
        logger.info(f"Connection #{self.connection_id}: Connecting to {self.base_url} ({len(self._subscriptions)} streams)")
        
        try:
            async with websockets.connect(
                url,
                close_timeout=self.CLOSE_TIMEOUT,
                ping_interval=self.PING_INTERVAL,
                ping_timeout=self.PING_TIMEOUT,
                max_queue=self.MAX_QUEUE_SIZE
            ) as websocket:
                self._ws = websocket
                self._connected = True
                self._reconnect_attempts = 0
                
                logger.info(f"Connection #{self.connection_id}: Connected successfully ({len(self.symbols)} symbols)")
                
                # Message loop with error handling
                try:
                    async for message in websocket:
                        if self._should_stop:
                            break
                        if self._on_message_callback:
                            try:
                                await self._on_message_callback(message, self.connection_id)
                            except Exception as msg_error:
                                logger.error(f"Connection #{self.connection_id}: Message processing error: {msg_error}")
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"Connection #{self.connection_id}: Closed by server: {e}")
                    raise
                except asyncio.CancelledError:
                    logger.info(f"Connection #{self.connection_id}: Connection task cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Connection #{self.connection_id}: Unexpected error in message loop: {e}")
                    raise
                    
        except websockets.exceptions.InvalidURI as e:
            logger.error(f"Connection #{self.connection_id}: Invalid URI: {e}")
            raise
        except (OSError, ConnectionError) as e:
            logger.error(f"Connection #{self.connection_id}: Network error: {e}")
            raise
        except Exception as e:
            logger.error(f"Connection #{self.connection_id}: Connection failed: {type(e).__name__}: {e}")
            raise
        finally:
            self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected


class WebSocketCollector:
    """
    Multi-connection WebSocket data collector.
    Splits symbols across multiple connections to avoid URI length limits.
    """
    
    LIVE_WS_URL = "wss://fstream.binance.com/ws"
    TESTNET_WS_URL = "wss://stream.binancefuture.com/ws"
    
    # Max symbols per connection to avoid HTTP 414
    MAX_SYMBOLS_PER_CONNECTION = 100
    
    def __init__(self):
        if settings.BINANCE_TESTNET:
            self.base_url = self.TESTNET_WS_URL
        else:
            self.base_url = self.LIVE_WS_URL
        
        self._connections: List[SingleWebSocketConnection] = []
        self._connected = False
        
        # Event callbacks
        self._on_kline_callback: Optional[Callable] = None
        self._on_trade_callback: Optional[Callable] = None
        self._on_book_ticker_callback: Optional[Callable] = None
        self._on_error_callback: Optional[Callable] = None
        
        # All symbols being tracked
        self._all_symbols: Set[str] = set()

        # Kline interval for subscriptions
        self._kline_interval: str = "12h"
        
        # Metrics
        self._latency_metrics = LatencyMetrics()
        self._last_data_time: Optional[datetime] = None
        
        # Connection health monitoring
        self._connection_errors: Dict[int, int] = {}
        self._last_health_check: Optional[datetime] = None
        
        if websockets is None:
            raise ImportError("websockets package is required. Install with: pip install websockets")
        
        logger.info(f"WebSocketCollector initialized for {settings.ENVIRONMENT}")
    
    def on_kline(self, callback: Callable[[MarketData], None]):
        """Register callback for kline events"""
        import logging
        logger = logging.getLogger("autobot.data.websocket")
        logger.info(f"[on_kline] Registering callback: {callback is not None}")
        self._on_kline_callback = callback
        logger.info(f"[on_kline] After register: {self._on_kline_callback is not None}")
    
    def on_trade(self, callback: Callable[[MarketData], None]):
        """Register callback for trade events"""
        self._on_trade_callback = callback
    
    def on_book_ticker(self, callback: Callable[[MarketData], None]):
        """Register callback for book ticker events"""
        self._on_book_ticker_callback = callback
    
    def on_error(self, callback: Callable[[Exception], None]):
        """Register callback for error events"""
        self._on_error_callback = callback
    
    def subscribe_klines(self, symbols: list, interval: str = "1m"):
        """Subscribe to kline stream for symbols"""
        self._all_symbols.update(symbols)
        self._kline_interval = interval  # Store the interval
        logger.info(f"Subscribing to klines for {len(symbols)} symbols (total: {len(self._all_symbols)})")
    
    def subscribe_trades(self, symbols: list):
        """Subscribe to trade stream for symbols"""
        self._all_symbols.update(symbols)
        logger.info(f"Subscribing to trades for {len(symbols)} symbols")
    
    def subscribe_book_ticker(self, symbols: list):
        """Subscribe to book ticker stream for symbols"""
        self._all_symbols.update(symbols)
        logger.info(f"Subscribing to book ticker for {len(symbols)} symbols")
    
    async def start(self):
        """Start all WebSocket connections"""
        
        logger.info(f"Starting WebSocket collector for {len(self._all_symbols)} symbols...")
        
        # Split symbols into batches
        symbol_list = list(self._all_symbols)
        batch_size = self.MAX_SYMBOLS_PER_CONNECTION
        
        batches = []
        for i in range(0, len(symbol_list), batch_size):
            batch = symbol_list[i:i + batch_size]
            batches.append(batch)
        
        logger.info(f"Creating {len(batches)} WebSocket connections ({batch_size} symbols per connection)")
        
        # Create connections for each batch
        for i, batch in enumerate(batches):
            conn = SingleWebSocketConnection(
                symbols=batch,
                connection_id=i + 1,
                base_url=self.base_url,
                on_message_callback=self._process_message,
                on_error_callback=self._handle_error
            )
            
            # Subscribe to klines and book ticker for this batch
            conn.subscribe_klines(batch, interval=self._kline_interval)
            conn.subscribe_book_ticker(batch)
            
            self._connections.append(conn)
            self._connection_errors[i + 1] = 0
        
        # Start all connections
        tasks = []
        for conn in self._connections:
            await conn.start()
            # Small delay between connections to avoid rate limiting
            await asyncio.sleep(0.5)
        
        self._connected = True
        
        # Start health check task
        health_check_task = asyncio.create_task(self._health_check_loop())
        
        # Wait for all connections to stay alive
        try:
            while self._connected:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("WebSocket collector main task cancelled")
            health_check_task.cancel()
            await self.disconnect()
    
    async def disconnect(self):
        """Disconnect all WebSocket connections"""
        
        logger.info("Disconnecting WebSocket...")
        self._connected = False
        
        for conn in self._connections:
            await conn.stop()
        
        self._connections.clear()
        logger.info("All WebSocket connections disconnected")
    
    async def _health_check_loop(self):
        """Monitor connection health"""
        while self._connected:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                now = datetime.now(timezone.utc)
                if self._last_data_time:
                    data_age = (now - self._last_data_time).total_seconds()
                    if data_age > 60:  # No data for 60 seconds
                        logger.warning(f"No data received for {data_age:.0f} seconds")
                
                # Log connection status
                connected_count = sum(1 for c in self._connections if c.is_connected)
                logger.debug(f"Health check: {connected_count}/{len(self._connections)} connections active")
                
            except asyncio.CancelledError:
                break
    
    async def _process_message(self, message: str, connection_id: int):
        """Process incoming WebSocket message from any connection"""
        
        received_at = datetime.now(timezone.utc)
        
        try:
            data = json.loads(message)
            
            # Get event time for latency calculation
            event_time = data.get("E", 0)
            if event_time:
                event_dt = datetime.fromtimestamp(event_time / 1000, tz=timezone.utc)
                latency_ms = (received_at - event_dt).total_seconds() * 1000
                self._latency_metrics.update(latency_ms)
            else:
                latency_ms = 0.0
            
            self._last_data_time = received_at
            
            # Reset error counter on successful message
            if connection_id in self._connection_errors:
                self._connection_errors[connection_id] = 0
            
            # Route to appropriate handler by event type
            event_type = data.get("e", "")
            
            # DEBUG: Log routing with instance ID
            import logging
            logger = logging.getLogger("autobot.data.websocket")
            logger.info(f"[ROUTE] ws_id={id(self)}, event_type={event_type}, has_kline={self._on_kline_callback is not None}")
            
            if event_type == "kline" and self._on_kline_callback:
                await self._handle_kline(data, received_at, latency_ms)
            elif event_type == "aggTrade" and self._on_trade_callback:
                await self._handle_trade(data, received_at, latency_ms)
            elif event_type == "bookTicker" and self._on_book_ticker_callback:
                await self._handle_book_ticker(data, received_at, latency_ms)
            
        except json.JSONDecodeError as e:
            logger.error(f"Connection #{connection_id}: JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Connection #{connection_id}: Message processing error: {e}")
    
    async def _handle_error(self, error: Exception):
        """Handle WebSocket error"""
        logger.error(f"WebSocket error: {error}")
        if self._on_error_callback:
            try:
                await self._on_error_callback(error)
            except Exception as cb_error:
                logger.error(f"Error callback failed: {cb_error}")
    
    async def _handle_kline(self, data: dict, received_at: datetime, latency_ms: float):
        """Handle kline data"""
        try:
            kline = data.get("k", {})
            symbol = data.get("s", "")
            
            market_data = MarketData(
                symbol=symbol,
                stream_type=StreamType.KLINE,
                timestamp=datetime.fromtimestamp(kline.get("t", 0) / 1000, tz=timezone.utc),
                received_at=received_at,
                latency_ms=latency_ms,
                open=float(kline.get("o", 0)),
                high=float(kline.get("h", 0)),
                low=float(kline.get("l", 0)),
                close=float(kline.get("c", 0)),
                volume=float(kline.get("v", 0)),
                is_kline_closed=kline.get("x", False)
            )
            
            await self._handle_callback(self._on_kline_callback, market_data)
            
        except Exception as e:
            logger.error(f"Error handling kline: {e}")
    
    async def _handle_trade(self, data: dict, received_at: datetime, latency_ms: float):
        """Handle trade data"""
        try:
            market_data = MarketData(
                symbol=data.get("s", ""),
                stream_type=StreamType.AGG_TRADE,
                timestamp=datetime.fromtimestamp(data.get("T", 0) / 1000, tz=timezone.utc),
                received_at=received_at,
                latency_ms=latency_ms,
                trade_id=data.get("a", 0),
                trade_price=float(data.get("p", 0)),
                trade_qty=float(data.get("q", 0))
            )
            
            await self._handle_callback(self._on_trade_callback, market_data)
            
        except Exception as e:
            logger.error(f"Error handling trade: {e}")
    
    async def _handle_book_ticker(self, data: dict, received_at: datetime, latency_ms: float):
        """Handle book ticker data"""
        try:
            market_data = MarketData(
                symbol=data.get("s", ""),
                stream_type=StreamType.BOOK_TICKER,
                timestamp=datetime.fromtimestamp(data.get("E", 0) / 1000, tz=timezone.utc),
                received_at=received_at,
                latency_ms=latency_ms,
                best_bid=float(data.get("b", 0)),
                best_ask=float(data.get("a", 0)),
                bid_qty=float(data.get("B", 0)),
                ask_qty=float(data.get("A", 0))
            )
            
            await self._handle_callback(self._on_book_ticker_callback, market_data)
            
        except Exception as e:
            logger.error(f"Error handling book ticker: {e}")
    
    async def _handle_callback(self, callback: Callable, *args):
        """Safely execute callback"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"Callback error: {e}", exc_info=True)
    
    @property
    def latency_metrics(self) -> LatencyMetrics:
        return self._latency_metrics
    
    @property
    def is_connected(self) -> bool:
        return self._connected and any(c.is_connected for c in self._connections)
