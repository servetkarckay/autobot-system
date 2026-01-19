"""
AUTOBOT Tests - Risk Controls
Unit tests for risk management and veto chain
"""
import pytest
from datetime import datetime

from core.state import SystemState, SystemStatus, MarketRegime, TradeSignal, Position
from core.risk.pre_trade_veto import PreTradeVetoChain, VetoConfig


@pytest.fixture
def system_state():
    """Create a test system state"""
    return SystemState(
        status=SystemStatus.RUNNING,
        equity=10000.0,
        peak_equity=10000.0,
        current_drawdown_pct=0.0,
        daily_pnl_pct=0.0,
        open_positions={}
    )


@pytest.fixture
def veto_config():
    """Create test veto configuration"""
    return VetoConfig(
        max_position_size_usdt=1000.0,
        max_positions=5,
        correlation_threshold=0.8,
        max_correlation_exposure_pct=3.0,
        max_drawdown_pct=15.0,
        daily_loss_limit_pct=3.0
    )


@pytest.fixture
def veto_chain(veto_config):
    """Create veto chain instance"""
    return PreTradeVetoChain(veto_config)


def test_position_size_veto(veto_chain, system_state):
    """Test that oversized positions are vetoed"""
    
    signal = TradeSignal(
        symbol="BTCUSDT",
        action="PROPOSE_LONG",
        bias_score=0.8,
        confidence=0.7,
        strategy_name="test",
        regime=MarketRegime.BULL_TREND
    )
    
    # Position too large (should be vetoed)
    result = veto_chain.evaluate(signal, system_state, quantity=0.5, price=50000)
    assert not result.approved
    assert result.veto_stage == "position_size"
    
    # Acceptable size
    result = veto_chain.evaluate(signal, system_state, quantity=0.01, price=50000)
    assert result.approved


def test_max_positions_veto(veto_chain, system_state):
    """Test that max positions limit is enforced"""
    
    signal = TradeSignal(
        symbol="ETHUSDT",
        action="PROPOSE_LONG",
        bias_score=0.8,
        confidence=0.7,
        strategy_name="test",
        regime=MarketRegime.BULL_TREND
    )
    
    # Fill up to max positions
    for i in range(5):
        system_state.open_positions[f"SYMBOL{i}"] = Position(
            symbol=f"SYMBOL{i}",
            side="LONG",
            quantity=1.0,
            entry_price=100.0,
            current_price=100.0,
            unrealized_pnl=0.0
        )
    
    result = veto_chain.evaluate(signal, system_state, quantity=1.0, price=100.0)
    assert not result.approved
    assert result.veto_stage == "max_positions"


def test_drawdown_veto(veto_chain, system_state):
    """Test that excessive drawdown triggers veto"""
    
    system_state.current_drawdown_pct = 16.0  # Over the 15% limit
    
    signal = TradeSignal(
        symbol="BTCUSDT",
        action="PROPOSE_LONG",
        bias_score=0.8,
        confidence=0.7,
        strategy_name="test",
        regime=MarketRegime.BULL_TREND
    )
    
    result = veto_chain.evaluate(signal, system_state, quantity=0.01, price=50000)
    assert not result.approved
    assert result.veto_stage == "drawdown"


def test_daily_loss_veto(veto_chain, system_state):
    """Test that daily loss limit triggers veto"""
    
    system_state.daily_pnl_pct = -4.0  # Over the -3% limit
    
    signal = TradeSignal(
        symbol="BTCUSDT",
        action="PROPOSE_LONG",
        bias_score=0.8,
        confidence=0.7,
        strategy_name="test",
        regime=MarketRegime.BULL_TREND
    )
    
    result = veto_chain.evaluate(signal, system_state, quantity=0.01, price=50000)
    assert not result.approved
    assert result.veto_stage == "daily_loss"
