"""
AUTOBOT System State Management and Persistence v1.3
Combines dataclasses for system state representation and persistence logic to Redis.

FIXES:
- Added Redis connection pool for better performance
- Added retry logic for Redis operations
- Added thread-safe operations
- Added better error handling
- Fixed syntax errors
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Literal, Optional, Dict, List, Any
from enum import Enum
import json
import logging
import threading
import time

try:
    import redis
    from redis.connection import ConnectionPool
    from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
except ImportError:
    redis = None
    ConnectionPool = None
    RedisError = Exception
    RedisConnectionError = Exception

from config.settings import settings

logger = logging.getLogger("autobot.state_manager")


class SystemStatus(Enum):
    """System operational status"""
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    SAFE_MODE = "SAFE_MODE"
    HALTED = "HALTED"


class MarketRegime(Enum):
    """Detected market regime"""
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


class VolatilityRegime(Enum):
    """Volatility classification"""
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


@dataclass
class ExitMetadata:
    """Exit metadata for position"""
    adx_at_entry: float = 0.0
    adx_prev: float = 0.0
    regime_at_entry: MarketRegime = MarketRegime.UNKNOWN
    last_exit_check_ts: Optional[int] = None


@dataclass
class ExitSignal:
    """Exit sinyali"""
    should_exit: bool
    reason: str
    exit_type: Literal["REGIME_CHANGE", "MOMENTUM_LOSS", "DONCHIAN_BREAK", "STOP_LOSS", ""]
    urgency: Literal["IMMEDIATE", "NEXT_BAR", ""]


@dataclass
class Position:
    """Open position state"""
    symbol: str
    side: Literal["LONG", "SHORT"]
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    entry_time: datetime = field(default_factory=datetime.utcnow)
    strategy_name: str = ""
    regime_at_entry: MarketRegime = MarketRegime.UNKNOWN
    exit_metadata: ExitMetadata = field(default_factory=ExitMetadata)


@dataclass
class SystemState:
    """Complete system state for persistence and recovery"""
    status: SystemStatus = SystemStatus.RUNNING
    last_update: datetime = field(default_factory=datetime.utcnow)
    current_regime: MarketRegime = MarketRegime.UNKNOWN
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    symbol_regimes: Dict[str, MarketRegime] = field(default_factory=dict)
    equity: float = 0.0
    peak_equity: float = 0.0
    current_drawdown_pct: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    open_positions: Dict[str, Position] = field(default_factory=dict)
    strategy_weights: Dict[str, float] = field(default_factory=dict)
    stop_loss_multiplier: float = 2.5
    activation_threshold: float = 0.7
    daily_loss_limit_pct: float = 3.0
    max_drawdown_pct: float = 15.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    def update_symbol_regime(self, symbol: str, regime: MarketRegime):
        self.symbol_regimes[symbol] = regime

    def get_symbol_regime(self, symbol: str) -> MarketRegime:
        if symbol not in self.symbol_regimes:
            raise RuntimeError(f"Regime state missing for symbol: {symbol}")
        return self.symbol_regimes[symbol]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["last_update"] = self.last_update.isoformat()
        data["status"] = self.status.value
        data["current_regime"] = self.current_regime.value
        data["volatility_regime"] = self.volatility_regime.value
        data["symbol_regimes"] = {k: v.value for k, v in self.symbol_regimes.items()}
        
        serialized_positions = {}
        for symbol, pos in self.open_positions.items():
            pos_dict = {
                "symbol": pos.symbol, "side": pos.side, "quantity": pos.quantity,
                "entry_price": pos.entry_price, "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl, "stop_loss_price": pos.stop_loss_price,
                "take_profit_price": pos.take_profit_price, "entry_time": pos.entry_time.isoformat(),
                "strategy_name": pos.strategy_name, "regime_at_entry": pos.regime_at_entry.value,
                "exit_metadata": None
            }
            serialized_positions[symbol] = pos_dict
        data["open_positions"] = serialized_positions
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SystemState":
        if "last_update" in data and isinstance(data["last_update"], str):
            data["last_update"] = datetime.fromisoformat(data["last_update"])
        
        positions = {}
        for symbol, pos_data in data.get("open_positions", {}).items():
            if isinstance(pos_data.get("entry_time"), str):
                pos_data["entry_time"] = datetime.fromisoformat(pos_data["entry_time"])
            if isinstance(pos_data.get("regime_at_entry"), str):
                pos_data["regime_at_entry"] = MarketRegime[pos_data["regime_at_entry"]]
            if "exit_metadata" not in pos_data or pos_data["exit_metadata"] is None:
                pos_data["exit_metadata"] = ExitMetadata()
            positions[symbol] = Position(**pos_data)
        data["open_positions"] = positions
        
        if "status" in data and isinstance(data["status"], str):
            data["status"] = SystemStatus[data["status"]]
        if "current_regime" in data and isinstance(data["current_regime"], str):
            data["current_regime"] = MarketRegime[data["current_regime"]]
        if "volatility_regime" in data and isinstance(data["volatility_regime"], str):
            data["volatility_regime"] = VolatilityRegime[data["volatility_regime"]]
        
        # FIXED: Proper if-else structure
        if "symbol_regimes" in data:
            symbol_regimes = {}
            for sym, reg in data["symbol_regimes"].items():
                if isinstance(reg, str):
                    symbol_regimes[sym] = MarketRegime[reg]
                else:
                    symbol_regimes[sym] = reg
            data["symbol_regimes"] = symbol_regimes
        else:
            data["symbol_regimes"] = {}
        
        return cls(**data)


@dataclass
class TradeSignal:
    """Generated trading signal from Decision Engine"""
    symbol: str
    action: Literal["PROPOSE_LONG", "PROPOSE_SHORT", "NEUTRAL", "CLOSE"]
    bias_score: float
    confidence: float
    strategy_name: str
    regime: MarketRegime
    timestamp: datetime = field(default_factory=datetime.utcnow)
    atr: float = 0.0
    suggested_price: float = 0.0
    suggested_quantity: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class VetoResult:
    """Result of risk veto chain evaluation"""
    approved: bool
    veto_reason: str | None = None
    veto_stage: str | None = None
    adjusted_quantity: float | None = None
    adjusted_price: float | None = None


class StateManager:
    """Manages system state persistence to Redis with connection pooling"""
    
    STATE_KEY = "autobot:system_state"
    MAX_RETRIES = 3
    RETRY_DELAY = 0.5
    
    def __init__(self):
        self._redis_client: Optional["redis.Redis"] = None
        self._connection_pool: Optional["ConnectionPool"] = None
        self._lock = threading.RLock()
        self._connect_redis()
    
    def _connect_redis(self):
        """Establish connection to Redis with connection pooling"""
        if redis is None:
            logger.error("redis package not installed")
            return
        
        try:
            password_val = None
            if settings.REDIS_PASSWORD:
                password_val = settings.REDIS_PASSWORD.get_secret_value()
            
            self._connection_pool = ConnectionPool(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=password_val,
                db=settings.REDIS_DB,
                max_connections=10,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                decode_responses=True
            )
            
            self._redis_client = redis.Redis(connection_pool=self._connection_pool)
            self._redis_client.ping()
            logger.info(f"Connected to Redis with connection pool at {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._redis_client = None
            self._connection_pool = None
    
    def _retry_operation(self, operation, *args, **kwargs):
        """Retry Redis operations with exponential backoff"""
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return operation(*args, **kwargs)
            except RedisError as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"Redis operation failed (attempt {attempt + 1}/{self.MAX_RETRIES}), retrying in {delay}s: {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"Redis operation failed after {self.MAX_RETRIES} attempts: {e}")
        raise last_error
    
    def save_state(self, state: SystemState) -> bool:
        """Save system state to Redis with retry logic"""
        with self._lock:
            if self._redis_client is None:
                logger.warning("Redis not connected, state not saved")
                return False
            
            try:
                state_dict = state.to_dict()
                state_json = json.dumps(state_dict)
                
                def _save():
                    self._redis_client.setex(
                        self.STATE_KEY,
                        settings.REDIS_STATE_TTL,
                        state_json
                    )
                
                self._retry_operation(_save)
                logger.debug(f"State saved to Redis at {datetime.utcnow().isoformat()}")
                return True
            except Exception as e:
                logger.error(f"Failed to save state to Redis: {e}")
                return False
    
    def load_state(self) -> Optional[SystemState]:
        """Load system state from Redis with retry logic"""
        with self._lock:
            if self._redis_client is None:
                logger.warning("Redis not connected, using default state")
                return None
            
            try:
                def _load():
                    return self._redis_client.get(self.STATE_KEY)
                
                state_json = self._retry_operation(_load)
                if state_json is None:
                    logger.info("No saved state found in Redis")
                    return None
                
                state_dict = json.loads(state_json)
                state = SystemState.from_dict(state_dict)
                logger.info(f"State loaded from Redis: status={state.status}, positions={len(state.open_positions)}")
                return state
            except Exception as e:
                logger.error(f"Failed to load state from Redis: {e}")
                return None
    
    def clear_state(self) -> bool:
        """Clear saved state from Redis with retry logic"""
        with self._lock:
            if self._redis_client is None:
                return False
            
            try:
                def _clear():
                    self._redis_client.delete(self.STATE_KEY)
                
                self._retry_operation(_clear)
                logger.info("State cleared from Redis")
                return True
            except Exception as e:
                logger.error(f"Failed to clear state: {e}")
                return False
    
    def is_connected(self) -> bool:
        """Check if Redis is connected"""
        if self._redis_client is None:
            return False
        try:
            self._redis_client.ping()
            return True
        except Exception:
            return False
    
    def cleanup(self):
        """Clean up Redis connections"""
        with self._lock:
            if self._connection_pool:
                try:
                    self._connection_pool.disconnect()
                    logger.info("Redis connection pool closed")
                except Exception as e:
                    logger.error(f"Error closing Redis pool: {e}")
            self._redis_client = None
            self._connection_pool = None


state_manager = StateManager()
