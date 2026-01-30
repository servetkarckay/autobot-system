"""
Binance API Rate Limiter
Prevents IP bans by respecting rate limits
"""
import asyncio
import time
import logging
from typing import Optional
from collections import deque
from binance.exceptions import BinanceAPIException

logger = logging.getLogger("autobot.rate_limiter")


class RateLimiter:
    """
    Token bucket rate limiter for Binance API
    
    Binance Futures Limits:
    - 1200 request weight per minute
    - 2400 order weight per minute
    """
    
    ENDPOINT_WEIGHTS = {
        "futures_create_order": 10,
        "futures_cancel_order": 10,
        "futures_change_leverage": 50,
        "futures_position_information": 5,
        "futures_account": 5,
        "futures_exchange_info": 10,
    }
    
    REQUEST_WEIGHT_LIMIT = 1200
    SAFETY_FACTOR = 0.8
    
    def __init__(self):
        self._request_weight = int(self.REQUEST_WEIGHT_LIMIT * self.SAFETY_FACTOR)
        self._max_request_weight = self._request_weight
        self._last_refill = time.time()
        self._lock = asyncio.Lock()
        self._request_history = deque(maxlen=100)
        
        logger.info(
            f"[RATE LIMITER] Initialized: {self._request_weight}/{self.REQUEST_WEIGHT_LIMIT} "
            f"weight per minute"
        )
    
    async def acquire(self, endpoint: str, weight: Optional[int] = None) -> bool:
        async with self._lock:
            await self._refill()
            
            if weight is None:
                weight = self.ENDPOINT_WEIGHTS.get(endpoint, 1)
            
            if self._request_weight >= weight:
                self._request_weight -= weight
                self._request_history.append({
                    "time": time.time(),
                    "endpoint": endpoint,
                    "weight": weight,
                    "remaining": self._request_weight
                })
                return True
            else:
                wait_time = self._calculate_wait_time(weight)
                logger.warning(
                    f"[RATE LIMIT] {endpoint}: Need {weight}, have {self._request_weight}. "
                    f"Wait {wait_time:.1f}s"
                )
                return False
    
    async def _refill(self):
        now = time.time()
        elapsed = now - self._last_refill
        
        if elapsed >= 1.0:
            refill_amount = (elapsed / 60.0) * self._max_request_weight
            self._request_weight = min(
                self._max_request_weight,
                self._request_weight + refill_amount
            )
            self._last_refill = now
    
    def _calculate_wait_time(self, required_weight: float) -> float:
        deficit = required_weight - self._request_weight
        refill_rate = self._max_request_weight / 60.0
        return deficit / refill_rate if refill_rate > 0 else 60.0
    
    async def wait_if_needed(self, endpoint: str, weight: Optional[int] = None):
        while True:
            acquired = await self.acquire(endpoint, weight)
            if acquired:
                return
            
            wait_time = self._calculate_wait_time(
                self.ENDPOINT_WEIGHTS.get(endpoint, weight or 1)
            )
            logger.info(f"[RATE LIMIT] Waiting {wait_time:.1f}s before {endpoint}")
            await asyncio.sleep(wait_time)
    
    def get_status(self) -> dict:
        return {
            "available_weight": self._request_weight,
            "max_weight": self._max_request_weight,
            "usage_percent": (1 - self._request_weight / self._max_request_weight) * 100,
        }
    
    def handle_rate_limit_error(self, error: BinanceAPIException) -> bool:
        if error.code == -1003:
            logger.warning("[RATE LIMIT] Binance -1003: Too many requests. Backing off...")
            return True
        elif error.code == -1004:
            logger.warning(f"[RATE LIMIT] Duplicate request: {error.message}")
            return True
        return False


# Global instance
rate_limiter = RateLimiter()
