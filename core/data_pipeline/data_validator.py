"""
AUTOBOT Data Pipeline - Data Validator
Performs sanity checks on incoming market data
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from core.data_pipeline.websocket_collector import MarketData, StreamType

logger = logging.getLogger("autobot.data.validator")


class DataValidator:
    """Validates incoming market data for anomalies"""
    
    # Validation thresholds
    MAX_PRICE_CHANGE_PCT = 20.0  # Max allowed price change in single update
    MAX_VOLUME_SPIKE = 10.0  # Max volume spike factor
    TIMESTAMP_TOLERANCE_MS = 10000  # Max acceptable timestamp offset
    MIN_PRICE = 0.000001  # Minimum valid price
    MAX_PRICE = 10000000  # Maximum valid price
    
    # Previous prices for spike detection (per symbol)
    _previous_prices: dict = {}
    _previous_volumes: dict = {}
    
    def __init__(self):
        self._rejected_count = 0
        self._accepted_count = 0
    
    def validate(self, data: MarketData) -> Tuple[bool, Optional[str]]:
        """
        Validate market data.
        
        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        
        # Timestamp sanity check - enabled for production only
        if not settings.is_testnet:  # Skip validation for testnet
            if not self._validate_timestamp(data):
                reason = f"Timestamp sanity check failed: latency={data.latency_ms:.2f}ms"
                logger.warning(reason)
                self._rejected_count += 1
                return False, reason
        # Price sanity check (kline)
        if data.stream_type == StreamType.KLINE:
            if not self._validate_kline(data):
                reason = f"Kline sanity check failed for {data.symbol}"
                logger.warning(reason)
                self._rejected_count += 1
                return False, reason
        
        # Trade sanity check
        if data.stream_type == StreamType.AGG_TRADE:
            if not self._validate_trade(data):
                reason = f"Trade sanity check failed for {data.symbol}"
                logger.warning(reason)
                self._rejected_count += 1
                return False, reason
        
        # All checks passed
        self._accepted_count += 1
        return True, None
    
    def _validate_timestamp(self, data: MarketData) -> bool:
        """Validate timestamp is within acceptable bounds"""
        
        # Check latency is reasonable (not from far future/past)
        if abs(data.latency_ms) > self.TIMESTAMP_TOLERANCE_MS:
            return False
        
        # Check timestamp is not too far from current time
        now = datetime.now(timezone.utc)
        time_diff = abs((now - data.timestamp).total_seconds())
        
        if time_diff > 60:  # More than 1 minute off
            return False
        
        return True
    
    def _validate_kline(self, data: MarketData) -> bool:
        """Validate kline/candlestick data"""
        
        # Check OHLC logic
        if data.high < data.low:
            logger.error(f"Invalid OHLC: high ({data.high}) < low ({data.low})")
            return False
        
        if data.close < data.low or data.close > data.high:
            logger.error(f"Invalid OHLC: close ({data.close}) outside high-low range")
            return False
        
        if data.open < data.low or data.open > data.high:
            logger.error(f"Invalid OHLC: open ({data.open}) outside high-low range")
            return False
        
        # Check price bounds
        if not (self.MIN_PRICE <= data.close <= self.MAX_PRICE):
            logger.error(f"Price out of bounds: {data.close}")
            return False
        
        # Check for price spike
        if data.symbol in self._previous_prices:
            prev_price = self._previous_prices[data.symbol]
            change_pct = abs((data.close - prev_price) / prev_price) * 100
            
            if change_pct > self.MAX_PRICE_CHANGE_PCT:
                logger.error(f"Price spike detected: {change_pct:.2f}% change")
                return False
        
        # Update previous price
        self._previous_prices[data.symbol] = data.close
        
        return True
    
    def _validate_trade(self, data: MarketData) -> bool:
        """Validate trade data"""
        
        if data.trade_price is None or data.trade_qty is None:
            return False
        
        # Check price bounds
        if not (self.MIN_PRICE <= data.trade_price <= self.MAX_PRICE):
            logger.error(f"Trade price out of bounds: {data.trade_price}")
            return False
        
        # Check quantity is positive
        if data.trade_qty <= 0:
            logger.error(f"Invalid trade quantity: {data.trade_qty}")
            return False
        
        return True
    
    def get_stats(self) -> dict:
        """Get validation statistics"""
        
        total = self._accepted_count + self._rejected_count
        
        return {
            "accepted": self._accepted_count,
            "rejected": self._rejected_count,
            "total": total,
            "rejection_rate": self._rejected_count / total if total > 0 else 0
        }
