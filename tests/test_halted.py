"""
HALTED DURUMU TESTİ - Daily Loss Limit
"""
import sys
import os
sys.path.insert(0, '/root/autobot_system')
os.chdir('/root/autobot_system')

from core.risk.pre_trade_veto import PreTradeVetoChain, VetoConfig
from core.state import TradeSignal, SystemState, SystemStatus, Position, MarketRegime
from datetime import datetime, timezone

print("="*60)
print("HALTED DURUMU TESTİ - Daily Loss Limit")
print("="*60)

config = VetoConfig(
    max_position_size_usdt=1000.0, max_positions=5,
    correlation_threshold=0.8, max_correlation_exposure_pct=3.0,
    max_drawdown_pct=15.0, daily_loss_limit_pct=3.0
)

veto_chain = PreTradeVetoChain(config)

# Daily loss limit testi - %4 kayıp
state = SystemState(
    status=SystemStatus.RUNNING,
    equity=9600.0,
    peak_equity=10000.0,
    daily_pnl_pct=-4.0  # %4 günlük kayıp (limit %3)
)

print(f"Daily PnL: {state.daily_pnl_pct}%")
print(f"Daily Loss Limit: {config.daily_loss_limit_pct}%")

signal = TradeSignal(
    symbol="BTCUSDT", action="PROPOSE_LONG",
    bias_score=0.8, confidence=0.9,
    strategy_name="test", regime=MarketRegime.BULL_TREND,
    timestamp=datetime.now(timezone.utc)
)

result = veto_chain.evaluate(signal, state, 0.01, 93000.0)
print(f"Result: {'✗ VETOED (HALTED)' if not result.approved else '✓ APPROVED (FAIL!)'}")

if not result.approved:
    print(f"Veto Stage: {result.veto_stage}")
    print(f"Reason: {result.veto_reason}")

# Test 2: Drawdown
print("\n" + "-"*40)
print("TEST 2: MAX DRAWDOWN VETO")

state2 = SystemState(
    status=SystemStatus.RUNNING,
    equity=8400.0,
    peak_equity=10000.0,
    current_drawdown_pct=16.0  # %16 drawdown (limit %15)
)

print(f"Drawdown: {state2.current_drawdown_pct}%")
print(f"Max Drawdown Limit: {config.max_drawdown_pct}%")

result2 = veto_chain.evaluate(signal, state2, 0.01, 93000.0)
print(f"Result: {'✗ VETOED (HALTED)' if not result2.approved else '✓ APPROVED (FAIL!)'}")

if not result2.approved:
    print(f"Veto Stage: {result2.veto_stage}")

print("\n" + "="*60)
print("HALTED TESTLERİ " + ('BAŞARILI ✅' if not result.approved and not result2.approved else 'BAŞARISIZ ❌'))
print("="*60)
