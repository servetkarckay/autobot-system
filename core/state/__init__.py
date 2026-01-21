"""
AUTOBOT System State Management
Dataclasses for system state representation
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Literal, Optional, Dict, List
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


@dataclass
class SystemState:
    """Complete system state for persistence and recovery"""
    # System status
    status: SystemStatus = SystemStatus.RUNNING
    last_update: datetime = field(default_factory=datetime.utcnow)

    # Market state
    current_regime: MarketRegime = MarketRegime.UNKNOWN
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL

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

    def to_dict(self) -> dict:
        """Convert state to dictionary for JSON serialization"""
        data = asdict(self)
        # Handle datetime serialization
        data["last_update"] = self.last_update.isoformat()
        # Handle enum serialization
        data["status"] = self.status.value
        data["current_regime"] = self.current_regime.value
        data["volatility_regime"] = self.volatility_regime.value
        # Handle open positions
        for pos in self.open_positions.values():
            pos.entry_time = pos.entry_time.isoformat()
            pos.regime_at_entry = pos.regime_at_entry.value
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
            positions[symbol] = Position(**pos_data)
        data["open_positions"] = positions
        # Handle enums
        if "status" in data and isinstance(data["status"], str):
            data["status"] = SystemStatus[data["status"]]
        if "current_regime" in data and isinstance(data["current_regime"], str):
            data["current_regime"] = MarketRegime[data["current_regime"]]
        if "volatility_regime" in data and isinstance(data["volatility_regime"], str):
            data["volatility_regime"] = VolatilityRegime[data["volatility_regime"]]
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
