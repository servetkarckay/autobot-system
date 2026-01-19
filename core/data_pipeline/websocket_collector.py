"""
AUTOBOT Data Pipeline - WebSocket Collector
Real-time market data collection from Binance WebSocket
Event-driven architecture for low-latency decision making
"""
import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional, Dict, Any, Set
from enum import Enum
import websockets

from config.settings import settings
from core.notification.telegram_manager import notification_manager, NotificationPriority

logger = logging.getLogger("autobot.data.websocket")


class StreamType(Enum):
    """WebSocket stream types"""
    KLINE = "kline"
    AGG_TRADE = "aggTrade"
    BOOK_TICKER = "bookTicker"
    DEPTH = "depth"


@dataclass
class MarketData:
    """Normalized market data structure"""
    symbol: str
    stream_type: StreamType
    timestamp: datetime  # Exchange timestamp
    received_at: datetime  # Local system timestamp
    latency_ms: float  # Calculated latency
    
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
        """Update metrics with new sample"""
        self.samples.append(latency_ms)
        self.current_latency_ms = latency_ms
        
        if len(self.samples) > 0:
            samples_list = list(self.samples)
            self.avg_latency_ms = sum(samples_list) / len(samples_list)
            self.max_latency_ms = max(samples_list)
            
            # Calculate percentiles
            sorted_samples = sorted(samples_list)
            self.p95_latency_ms = sorted_samples[int(len(sorted_samples) * 0.95)]
            self.p99_latency_ms = sorted_samples[int(len(sorted_samples) * 0.99)]


class WebSocketCollector:
    """
    Real-time WebSocket data collector with event-driven callbacks.
    Supports kline, aggregate trade, and book ticker streams.
    """
    
    # Base WebSocket URLs
    LIVE_WS_URL = "wss://fstream.binance.com/ws"
    TESTNET_WS_URL = "wss://stream.binancefuture.com/ws"
    
    def __init__(self):
        # Determine WebSocket URL based on settings
        if settings.BINANCE_TESTNET:
            self.base_url = self.TESTNET_WS_URL
        else:
            self.base_url = self.LIVE_WS_URL
        
        # Connection state
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = settings.WEBSOCKET_MAX_RECONNECT_ATTEMPTS
        
        # Subscribed streams
        self._subscribed_streams: Set[str] = set()
        self._symbols: Set[str] = set()
        
        # Data buffers (ring buffers for OHLCV)
        self._kline_buffers: Dict[str, deque] = {}  # symbol -> deque of klines
        self._buffer_size = 1000  # Keep last 1000 candles
        
        # Event callbacks (event-driven architecture)
        self._on_kline_callbacks: list = []
        self._on_trade_callbacks: list = []
        self._on_book_ticker_callbacks: list = []
        self._on_error_callbacks: list = []
        
        # Latency tracking
        self._latency_metrics = LatencyMetrics()
        
        # Data loss detection
        self._last_data_time: Dict[str, datetime] = {}
        self._data_loss_threshold = settings.DATA_LOSS_TIMEOUT  # seconds
        
        logger.info(f"WebSocketCollector initialized: {self.base_url}")
    
    def on_kline(self, callback: Callable[[MarketData], None]):
        """Register callback for kline events"""
        self._on_kline_callbacks.append(callback)
        logger.debug(f"Registered kline callback: {callback.__name__}")
    
    def on_trade(self, callback: Callable[[MarketData], None]):
        """Register callback for trade events"""
        self._on_trade_callbacks.append(callback)
        logger.debug(f"Registered trade callback: {callback.__name__}")
    
    def on_book_ticker(self, callback: Callable[[MarketData], None]):
        """Register callback for book ticker events"""
        self._on_book_ticker_callbacks.append(callback)
        logger.debug(f"Registered book ticker callback: {callback.__name__}")
    
    def on_error(self, callback: Callable[[Exception], None]):
        """Register callback for error events"""
        self._on_error_callbacks.append(callback)
        logger.debug(f"Registered error callback: {callback.__name__}")
    
    def subscribe_klines(self, symbols: list, interval: str = "1m"):
        """Subscribe to kline (candlestick) streams"""
        
        for symbol in symbols:
            symbol_lower = symbol.lower()
            stream = f"{symbol_lower}@kline_{interval}"
            self._subscribed_streams.add(stream)
            self._symbols.add(symbol)
            
            # Initialize buffer for this symbol
            if symbol not in self._kline_buffers:
                self._kline_buffers[symbol] = deque(maxlen=self._buffer_size)
        
        logger.info(f"Subscribed to klines for {symbols} ({interval})")
    
    def subscribe_agg_trades(self, symbols: list):
        """Subscribe to aggregate trade streams"""
        
        for symbol in symbols:
            symbol_lower = symbol.lower()
            stream = f"{symbol_lower}@aggTrade"
            self._subscribed_streams.add(stream)
            self._symbols.add(symbol)
        
        logger.info(f"Subscribed to agg trades for {symbols}")
    
    def subscribe_book_ticker(self, symbols: list):
        """Subscribe to book ticker (best bid/ask) streams"""
        
        for symbol in symbols:
            symbol_lower = symbol.lower()
            stream = f"{symbol_lower}@bookTicker"
            self._subscribed_streams.add(stream)
            self._symbols.add(symbol)
        
        logger.info(f"Subscribed to book ticker for {symbols}")
    
    def get_kline_buffer(self, symbol: str) -> deque:
        """Get kline buffer for a symbol"""
        return self._kline_buffers.get(symbol, deque(maxlen=self._buffer_size))
    
    def get_latest_kline(self, symbol: str) -> Optional[Dict]:
        """Get latest kline for a symbol"""
        buffer = self._kline_buffers.get(symbol)
        if buffer and len(buffer) > 0:
            return buffer[-1]
        return None
    
    def get_latency_metrics(self) -> LatencyMetrics:
        """Get current latency metrics"""
        return self._latency_metrics
    
    async def connect(self) -> bool:
        """Connect to WebSocket and start receiving data"""
        
        if not self._subscribed_streams:
            logger.error("No streams subscribed. Call subscribe_* methods first.")
            return False
        
        # Build combined stream URL
        streams = "/".join(sorted(self._subscribed_streams))
        url = f"{self.base_url}/{streams}"
        
        logger.info(f"Connecting to WebSocket: {url}")
        
        try:
            self._ws = await websockets.connect(url, ping_interval=20, ping_timeout=10)
            self._connected = True
            self._reconnect_attempts = 0
            
            logger.info("WebSocket connected successfully")
            notification_manager.send_info(
                title="WebSocket Connected",
                message=f"Connected to {len(self._subscribed_streams)} streams"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            await self._handle_connection_error(e)
            return False
    
    async def disconnect(self):
        """Disconnect from WebSocket"""
        
        self._connected = False
        
        if self._ws:
            try:
                await self._ws.close()
                logger.info("WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")
    
    async def start(self, process_callback: Optional[Callable] = None):
        """Start the WebSocket message loop"""
        
        if not await self.connect():
            logger.error("Failed to connect, not starting message loop")
            return
        
        logger.info("Starting WebSocket message loop...")
        
        try:
            async for message in self._ws:
                await self._process_message(message)
                
                # Data loss check
                await self._check_data_loss()
                
                # Optional callback for external processing
                if process_callback:
                    try:
                        await process_callback()
                    except Exception as e:
                        logger.error(f"Error in process callback: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            await self._reconnect()
        except Exception as e:
            logger.error(f"Error in message loop: {e}")
            await self._handle_connection_error(e)
    
    async def _process_message(self, message: str):
        """Process incoming WebSocket message"""
        
        try:
            data = json.loads(message)
            
            # Handle combined stream format
            if "stream" in data and "data" in data:
                stream = data["stream"]
                payload = data["data"]
            else:
                logger.warning(f"Unexpected message format: {message[:100]}")
                return
            
            # Determine stream type and dispatch
            if "@kline" in stream:
                await self._handle_kline(stream, payload)
            elif "@aggTrade" in stream:
                await self._handle_agg_trade(stream, payload)
            elif "@bookTicker" in stream:
                await self._handle_book_ticker(stream, payload)
            else:
                logger.debug(f"Unhandled stream type: {stream}")
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    async def _handle_kline(self, stream: str, payload: dict):
        """Handle kline (candlestick) data"""
        
        try:
            kline = payload.get("k", {})
            
            # Calculate latency
            event_time = datetime.fromtimestamp(payload["E"] / 1000, tz=timezone.utc)
            received_at = datetime.now(timezone.utc)
            latency_ms = (received_at - event_time).total_seconds() * 1000
            self._latency_metrics.update(latency_ms)
            
            # Extract symbol from stream
            symbol = stream.split("@")[0].upper()
            
            # Create normalized market data
            market_data = MarketData(
                symbol=symbol,
                stream_type=StreamType.KLINE,
                timestamp=event_time,
                received_at=received_at,
                latency_ms=latency_ms,
                open=float(kline.get("o", 0)),
                high=float(kline.get("h", 0)),
                low=float(kline.get("l", 0)),
                close=float(kline.get("c", 0)),
                volume=float(kline.get("v", 0)),
                is_kline_closed=kline.get("x", False)
            )
            
            # Update buffer
            if symbol in self._kline_buffers:
                kline_dict = {
                    "timestamp": event_time,
                    "open": market_data.open,
                    "high": market_data.high,
                    "low": market_data.low,
                    "close": market_data.close,
                    "volume": market_data.volume,
                    "is_closed": market_data.is_kline_closed
                }
                self._kline_buffers[symbol].append(kline_dict)
            
            # Update last data time for this symbol
            self._last_data_time[symbol] = received_at
            
            # Log latency warning if high
            if latency_ms > 500:
                logger.warning(f"High latency on {symbol}: {latency_ms:.2f}ms")
            
            # Trigger callbacks (EVENT-DRIVEN)
            for callback in self._on_kline_callbacks:
                try:
                    # Check if callback is async
                    if asyncio.iscoroutinefunction(callback):
                        await callback(market_data)
                    else:
                        callback(market_data)
                except Exception as e:
                    logger.error(f"Error in kline callback: {e}")
            
            # Special handling for kline close (TRIGGER DECISION)
            if market_data.is_kline_closed:
                logger.debug(f"Kline closed: {symbol} @ {market_data.close}")
                
        except Exception as e:
            logger.error(f"Error handling kline: {e}")
    
    async def _handle_agg_trade(self, stream: str, payload: dict):
        """Handle aggregate trade data"""
        
        try:
            event_time = datetime.fromtimestamp(payload["E"] / 1000, tz=timezone.utc)
            received_at = datetime.now(timezone.utc)
            latency_ms = (received_at - event_time).total_seconds() * 1000
            
            symbol = payload.get("s", "")
            
            market_data = MarketData(
                symbol=symbol,
                stream_type=StreamType.AGG_TRADE,
                timestamp=event_time,
                received_at=received_at,
                latency_ms=latency_ms,
                trade_id=int(payload.get("a", 0)),
                trade_price=float(payload.get("p", 0)),
                trade_qty=float(payload.get("q", 0))
            )
            
            # Update last data time
            self._last_data_time[symbol] = received_at
            
            # Trigger callbacks
            for callback in self._on_trade_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(market_data)
                    else:
                        callback(market_data)
                except Exception as e:
                    logger.error(f"Error in trade callback: {e}")
                    
        except Exception as e:
            logger.error(f"Error handling agg trade: {e}")
    
    async def _handle_book_ticker(self, stream: str, payload: dict):
        """Handle book ticker (best bid/ask) data"""
        
        try:
            event_time = datetime.fromtimestamp(payload["E"] / 1000, tz=timezone.utc)
            received_at = datetime.now(timezone.utc)
            latency_ms = (received_at - event_time).total_seconds() * 1000
            
            symbol = payload.get("s", "")
            
            market_data = MarketData(
                symbol=symbol,
                stream_type=StreamType.BOOK_TICKER,
                timestamp=event_time,
                received_at=received_at,
                latency_ms=latency_ms,
                best_bid=float(payload.get("b", 0)),
                best_ask=float(payload.get("a", 0)),
                bid_qty=float(payload.get("B", 0)),
                ask_qty=float(payload.get("A", 0))
            )
            
            # Update last data time
            self._last_data_time[symbol] = received_at
            
            # Trigger callbacks
            for callback in self._on_book_ticker_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(market_data)
                    else:
                        callback(market_data)
                except Exception as e:
                    logger.error(f"Error in book ticker callback: {e}")
                    
        except Exception as e:
            logger.error(f"Error handling book ticker: {e}")
    
    async def _check_data_loss(self):
        """Check for data loss on any subscribed symbol"""
        
        now = datetime.now(timezone.utc)
        
        for symbol in self._symbols:
            last_time = self._last_data_time.get(symbol)
            
            if last_time:
                elapsed = (now - last_time).total_seconds()
                
                if elapsed > self._data_loss_threshold:
                    logger.error(f"Data loss detected for {symbol}: {elapsed:.1f}s since last update")
                    notification_manager.send_error(
                        title="Data Loss Detected",
                        message=f"No data received for {symbol} in {elapsed:.1f}s",
                        symbol=symbol,
                        elapsed_seconds=f"{elapsed:.1f}"
                    )
    
    async def _reconnect(self):
        """Attempt to reconnect with exponential backoff"""
        
        self._reconnect_attempts += 1
        
        if self._reconnect_attempts > self._max_reconnect_attempts:
            logger.critical(f"Max reconnect attempts ({self._max_reconnect_attempts}) reached")
            notification_manager.send_critical(
                title="WebSocket Reconnection Failed",
                message=f"Failed to reconnect after {self._max_reconnect_attempts} attempts",
                attempts=self._max_reconnect_attempts
            )
            return
        
        delay = min(settings.WEBSOCKET_RECONNECT_DELAY * (2 ** self._reconnect_attempts), 60)
        
        logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
        await asyncio.sleep(delay)
        
        await self.connect()
    
    async def _handle_connection_error(self, error: Exception):
        """Handle connection errors"""
        
        logger.error(f"Connection error: {error}")
        
        for callback in self._on_error_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(error)
                else:
                    callback(error)
            except Exception as e:
                logger.error(f"Error in error callback: {e}")
