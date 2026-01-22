"""
AUTOBOT System State Management
Dataclasses for system state representation

GÜNCELLEME v2.0 - Exit Manager Entegrasyonu
- ExitMetadata eklendi
- Symbol bazlı regime takibi eklendi
- Position'a exit_metadata eklendi
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Literal, Optional, Dict, List, Any
from enum import Enum


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
    """
    Exit metadata for position

    Exit manager tarafından kullanılan metadata
    """
    adx_at_entry: float = 0.0
    adx_prev: float = 0.0
    regime_at_entry: MarketRegime = MarketRegime.UNKNOWN
    last_exit_check_ts: Optional[int] = None  # Bar timestamp (ms)


@dataclass
class ExitSignal:
    """
    Exit sinyali

    Exit manager tarafından döndürülen sinyal
    """
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

    # Exit metadata (runtime only, persist edilmez)
    exit_metadata: ExitMetadata = field(default_factory=ExitMetadata)


@dataclass
class SystemState:
    """Complete system state for persistence and recovery"""
    # System status
    status: SystemStatus = SystemStatus.RUNNING
    last_update: datetime = field(default_factory=datetime.utcnow)

    # Market state (GLOBAL - legacy, deprecated)
    current_regime: MarketRegime = MarketRegime.UNKNOWN
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL

    # Symbol bazlı regime takibi (YENİ - exit manager için)
    symbol_regimes: Dict[str, MarketRegime] = field(default_factory=dict)

    # Portfolio state
    equity: float = 0.0
    peak_equity: float = 0.0
    current_drawdown_pct: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0

    # Open positions
    open_positions: Dict[str, Position] = field(default_factory=dict)

    # Adaptive parameters (tunable by Adaptive Engine)
    strategy_weights: Dict[str, float] = field(default_factory=dict)
    stop_loss_multiplier: float = 2.5
    activation_threshold: float = 0.7

    # Risk limits
    daily_loss_limit_pct: float = 3.0
    max_drawdown_pct: float = 15.0

    # Performance tracking
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    def update_symbol_regime(self, symbol: str, regime: MarketRegime):
        """Sembol için regime güncelle"""
        self.symbol_regimes[symbol] = regime

    def get_symbol_regime(self, symbol: str) -> MarketRegime:
        """Sembol için regime al (yoksa UNKNOWN)"""
        return self.symbol_regimes.get(symbol, MarketRegime.UNKNOWN)

    def to_dict(self) -> dict:
        """Convert state to dictionary for JSON serialization"""
        data = asdict(self)
        # Handle datetime serialization
        data["last_update"] = self.last_update.isoformat()
        # Handle enum serialization
        data["status"] = self.status.value
        data["current_regime"] = self.current_regime.value
        data["volatility_regime"] = self.volatility_regime.value

        # Symbol regimes serialization
        data["symbol_regimes"] = {
            k: v.value for k, v in self.symbol_regimes.items()
        }

        # Handle open positions - serialize each position
        serialized_positions = {}
        for symbol, pos in self.open_positions.items():
            pos_dict = {
                "symbol": pos.symbol,
                "side": pos.side,
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "stop_loss_price": pos.stop_loss_price,
                "take_profit_price": pos.take_profit_price,
                "entry_time": pos.entry_time.isoformat(),
                "strategy_name": pos.strategy_name,
                "regime_at_entry": pos.regime_at_entry.value,
                "exit_metadata": None  # Runtime only, not persisted
            }
            serialized_positions[symbol] = pos_dict
        data["open_positions"] = serialized_positions

        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SystemState":
        """Create state from dictionary"""
        # Handle datetime deserialization
        if "last_update" in data and isinstance(data["last_update"], str):
            data["last_update"] = datetime.fromisoformat(data["last_update"])

        # Handle open positions
        positions = {}
        for symbol, pos_data in data.get("open_positions", {}).items():
            if isinstance(pos_data.get("entry_time"), str):
                pos_data["entry_time"] = datetime.fromisoformat(pos_data["entry_time"])
            if isinstance(pos_data.get("regime_at_entry"), str):
                pos_data["regime_at_entry"] = MarketRegime[pos_data["regime_at_entry"]]
            # Exit metadata yoksa oluştur
            if "exit_metadata" not in pos_data or pos_data["exit_metadata"] is None:
                pos_data["exit_metadata"] = ExitMetadata()
            positions[symbol] = Position(**pos_data)
        data["open_positions"] = positions

        # Handle enums
        if "status" in data and isinstance(data["status"], str):
            data["status"] = SystemStatus[data["status"]]
        if "current_regime" in data and isinstance(data["current_regime"], str):
            data["current_regime"] = MarketRegime[data["current_regime"]]
        if "volatility_regime" in data and isinstance(data["volatility_regime"], str):
            data["volatility_regime"] = VolatilityRegime[data["volatility_regime"]]

        # Handle symbol regimes
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
