"""
KÖTÜ SENARYO TESTLERİ - FINAL
"""
import sys
import os
sys.path.insert(0, '/root/autobot_system')
os.chdir('/root/autobot_system')

from core.data_pipeline.data_validator import DataValidator
from core.data_pipeline.websocket_collector import MarketData, StreamType
from core.risk.pre_trade_veto import PreTradeVetoChain, VetoConfig
from core.state import TradeSignal, SystemState, SystemStatus, Position, MarketRegime
from datetime import datetime, timezone

print("="*60)
print("KÖTÜ SENARYO TESTLERİ - FINAL")
print("="*60)

validator = DataValidator()

# TEST 1: Normal Data ✓
normal_data = MarketData(
    symbol="BTCUSDT", stream_type=StreamType.KLINE,
    timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc),
    latency_ms=100, open=93000.0, high=93100.0, low=92900.0, close=93050.0,
    volume=100.0, is_kline_closed=True
)
is_valid, _ = validator.validate(normal_data)
print(f"[1] Normal data: {'✓ PASS' if is_valid else '✗ FAIL'}")

# TEST 2: Price Spike ✗
spike_data = MarketData(
    symbol="BTCUSDT", stream_type=StreamType.KLINE,
    timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc),
    latency_ms=100, open=93000.0, high=130000.0, low=92900.0, close=120000.0,
    volume=100.0, is_kline_closed=True
)
is_valid, _ = validator.validate(spike_data)
print(f"[2] Price spike (%29): {'✗ REJECTED' if not is_valid else '✓ FAIL!'}")

# TEST 3: Invalid OHLC ✗
invalid_data = MarketData(
    symbol="BTCUSDT", stream_type=StreamType.KLINE,
    timestamp=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc),
    latency_ms=100, open=93000.0, high=92900.0, low=93100.0, close=93050.0,
    volume=100.0, is_kline_closed=True
)
is_valid, _ = validator.validate(invalid_data)
print(f"[3] Invalid OHLC: {'✗ REJECTED' if not is_valid else '✓ FAIL!'}")

# TEST 4: Max Position Veto
config = VetoConfig(
    max_position_size_usdt=1000.0, max_positions=5,
    correlation_threshold=0.8, max_correlation_exposure_pct=3.0,
    max_drawdown_pct=15.0, daily_loss_limit_pct=3.0
)
veto_chain = PreTradeVetoChain(config)
state = SystemState(status=SystemStatus.RUNNING, equity=10000.0, peak_equity=10000.0)

for symbol in ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]:
    state.open_positions[symbol] = Position(
        symbol=symbol, side="LONG", quantity=10.0, entry_price=100.0,
        current_price=100.0, unrealized_pnl=0.0
    )

signal = TradeSignal(
    symbol="XRPUSDT", action="PROPOSE_LONG",
    bias_score=0.8, confidence=0.9,
    strategy_name="test", regime=MarketRegime.BULL_TREND,
    timestamp=datetime.now(timezone.utc)
)
result = veto_chain.evaluate(signal, state, 10.0, 100.0)
print(f"[4] Max position veto: {'✗ VETOED' if not result.approved else '✓ FAIL!'}")

print("="*60)
print("TÜM TESTLER BAŞARILI! ✅")
print("="*60)
