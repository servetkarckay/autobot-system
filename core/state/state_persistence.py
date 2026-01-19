"""
AUTOBOT State Persistence Module
Handles saving and loading system state to Redis
"""
import json
import logging
from typing import Optional
from datetime import datetime

try:
    import redis
except ImportError:
    redis = None

from config.settings import settings
from core.state import SystemState

logger = logging.getLogger("autobot.state")


class StateManager:
    """Manages system state persistence to Redis"""
    
    STATE_KEY = "autobot:system_state"
    
    def __init__(self):
        self._redis_client: Optional["redis.Redis"] = None
        self._connect_redis()
    
    def _connect_redis(self):
        """Establish connection to Redis"""
        if redis is None:
            logger.error("redis package not installed")
            return
        
        try:
            self._redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD.get_secret_value() if settings.REDIS_PASSWORD else None,
                db=settings.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            self._redis_client.ping()
            logger.info(f"Connected to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._redis_client = None
    
    def save_state(self, state: SystemState) -> bool:
        """Save system state to Redis"""
        if self._redis_client is None:
            logger.warning("Redis not connected, state not saved")
            return False
        
        try:
            state_dict = state.to_dict()
            state_json = json.dumps(state_dict)
            
            self._redis_client.setex(
                self.STATE_KEY,
                settings.REDIS_STATE_TTL,
                state_json
            )
            logger.debug(f"State saved to Redis at {datetime.utcnow().isoformat()}")
            return True
        except Exception as e:
            logger.error(f"Failed to save state to Redis: {e}")
            return False
    
    def load_state(self) -> Optional[SystemState]:
        """Load system state from Redis"""
        if self._redis_client is None:
            logger.warning("Redis not connected, using default state")
            return None
        
        try:
            state_json = self._redis_client.get(self.STATE_KEY)
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
        """Clear saved state from Redis"""
        if self._redis_client is None:
            return False
        
        try:
            self._redis_client.delete(self.STATE_KEY)
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
        except:
            return False


# Global state manager instance
state_manager = StateManager()
