"""
AUTOBOT Tests - Execution Engine
Unit tests for order management
"""
import pytest
from datetime import datetime

from core.state import TradeSignal, MarketRegime
from core.execution.order_manager import OrderManager


@pytest.fixture
def order_manager():
    """Create order manager in dry-run mode"""
    return OrderManager(dry_run=True)


def test_dry_run_order_submission(order_manager):
    """Test that dry-run orders are logged but not submitted"""
    
    signal = TradeSignal(
        symbol="BTCUSDT",
        action="PROPOSE_LONG",
        bias_score=0.8,
        confidence=0.7,
        strategy_name="test",
        regime=MarketRegime.BULL_TREND
    )
    
    result = order_manager.submit_order(signal, quantity=0.01, price=50000)
    
    assert result.success
    assert result.order_id is not None
    assert result.order_id.startswith("DRY_")


def test_order_cancellation(order_manager):
    """Test order cancellation"""
    
    result = order_manager.cancel_order("test_order_123", "BTCUSDT")
    
    # In dry-run mode, cancellation should return True
    assert result is True
