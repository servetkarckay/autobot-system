"""
AUTOBOT Notification Manager - PRODUCTION READY
"""
import logging
import asyncio
import time
import json
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from threading import Lock
from pathlib import Path

try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError as e:
    Bot = None
    TelegramError = None
    TELEGRAM_AVAILABLE = False
    logging.error(f"telegram import failed: {e}")

from config.settings import settings

logger = logging.getLogger("autobot.notification.telegram")

RATE_LIMITS = {
    "INFO": {"max_per_minute": 60},
    "WARNING": {"max_per_minute": 10},
    "ERROR": {"max_per_minute": 5},
    "CRITICAL": {"max_per_10min": 1, "max_per_hour": 6},
    "HEARTBEAT": {"max_per_hour": 24},
}

class NotificationPriority(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    HEARTBEAT = "HEARTBEAT"

@dataclass
class NotificationMessage:
    priority: NotificationPriority
    title: str
    message: str
    metadata: Dict[str, Any]
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
    
    def get_event_key(self) -> str:
        key_parts = [self.title]
        if self.metadata:
            for k, v in sorted(self.metadata.items()):
                key_parts.append(f"{k}={v}")
        return ":".join(key_parts)

class TelegramNotificationManager:
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        with TelegramNotificationManager._lock:
            if hasattr(self, '_initialized') and self._initialized:
                return
            self._bot = None
            self._chat_id = None
            self._enabled = settings.TELEGRAM_NOTIFICATIONS_ENABLED and TELEGRAM_AVAILABLE
            self._send_history = {p.value: [] for p in NotificationPriority}
            self._critical_latch = {}
            self._latch_file = Path("/root/autobot_system/.critical_latch.json")
            self._load_latch_state()
            if self._enabled:
                self._initialize_bot()
            self._initialized = True
    
    def _load_latch_state(self):
        try:
            if self._latch_file.exists():
                with open(self._latch_file, 'r') as f:
                    self._critical_latch = json.load(f)
        except Exception:
            pass
    
    def _save_latch_state(self):
        try:
            with open(self._latch_file, 'w') as f:
                json.dump(self._critical_latch, f)
        except Exception:
            pass
    
    def _initialize_bot(self):
        try:
            token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
            self._bot = Bot(token=token)
            self._chat_id = settings.TELEGRAM_CHAT_ID
            logger.info(f"Telegram bot initialized: chat_id={self._chat_id}")
        except Exception as e:
            logger.error(f"Failed to init Telegram bot: {e}")
            self._enabled = False
    
    def _check_latch(self, event_key: str) -> bool:
        if event_key not in self._critical_latch:
            return False
        last_sent = self._critical_latch[event_key]
        if datetime.now(timezone.utc) - last_sent > timedelta(hours=24):
            del self._critical_latch[event_key]
            self._save_latch_state()
            return False
        return True
    
    def _set_latch(self, event_key: str):
        self._critical_latch[event_key] = datetime.now(timezone.utc)
        self._save_latch_state()
    
    def _check_rate_limit(self, priority: NotificationPriority) -> bool:
        now = time.time()
        history = self._send_history[priority.value]
        cutoff = now - 3600
        self._send_history[priority.value] = [t for t in history if t > cutoff]
        
        limits = RATE_LIMITS[priority.value]
        
        minute_ago = now - 60
        minute_count = sum(1 for t in history if t > minute_ago)
        if "max_per_minute" in limits and minute_count >= limits["max_per_minute"]:
            return False
        
        hour_count = len(history)
        if "max_per_hour" in limits and hour_count >= limits["max_per_hour"]:
            return False
        
        if priority == NotificationPriority.CRITICAL:
            ten_min_ago = now - 600
            ten_min_count = sum(1 for t in history if t > ten_min_ago)
            if ten_min_count >= limits.get("max_per_10min", 1):
                return False
        
        return True
    
    async def _send_async(self, notification: NotificationMessage) -> bool:
        if not self._enabled or self._bot is None:
            self._log_notification(notification)
            return False
        try:
            message = notification.format()
            await self._bot.send_message(chat_id=self._chat_id, text=message)
            logger.info(f"[TELEGRAM SENT] [{notification.priority.value}] {notification.title}")
            return True
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            self._log_notification(notification)
            return False
    
    def send_sync(self, notification: NotificationMessage) -> bool:
        if notification.priority == NotificationPriority.CRITICAL:
            event_key = notification.get_event_key()
            if self._check_latch(event_key):
                logger.warning(f"CRITICAL latched: {event_key}")
                return False
        
        if not self._check_rate_limit(notification.priority):
            logger.warning(f"Rate limited: {notification.priority.value}")
            self._log_notification(notification)
            return False
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(asyncio.wait_for(self._send_async(notification), timeout=10.0))
                if result:
                    self._send_history[notification.priority.value].append(time.time())
                    if notification.priority == NotificationPriority.CRITICAL:
                        self._set_latch(notification.get_event_key())
                return result
            except asyncio.TimeoutError:
                return False
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_async())
                except:
                    pass
                loop.close()
        except Exception as e:
            logger.error(f"send_sync error: {e}")
            self._log_notification(notification)
            return False
    
    def _log_notification(self, notification: NotificationMessage):
        log_level = {
            NotificationPriority.CRITICAL: logging.CRITICAL,
            NotificationPriority.ERROR: logging.ERROR,
            NotificationPriority.WARNING: logging.WARNING,
            NotificationPriority.INFO: logging.INFO,
            NotificationPriority.HEARTBEAT: logging.INFO,
        }
        logger.log(log_level.get(notification.priority, logging.INFO),
            f"[{notification.priority.value}] {notification.title}: {notification.message}")
    
    def send_critical(self, title: str, message: str, **metadata):
        notification = NotificationMessage(
            priority=NotificationPriority.CRITICAL,
            title=f"CRITICAL ALERT - {title}",
            message=message,
            metadata=metadata
        )
        return self.send_sync(notification)
    
    def send_error(self, title: str, message: str, **metadata):
        notification = NotificationMessage(
            priority=NotificationPriority.ERROR,
            title=f"SYSTEM ERROR - {title}",
            message=message,
            metadata=metadata
        )
        return self.send_sync(notification)
    
    def send_warning(self, title: str, message: str, **metadata):
        notification = NotificationMessage(
            priority=NotificationPriority.WARNING,
            title=f"WARNING - {title}",
            message=message,
            metadata=metadata
        )
        return self.send_sync(notification)
    
    def send_info(self, title: str, message: str, **metadata):
        notification = NotificationMessage(
            priority=NotificationPriority.INFO,
            title=title,
            message=message,
            metadata=metadata
        )
        return self.send_sync(notification)
    
    def send_heartbeat(self, system_state: Dict):
        notification = NotificationMessage(
            priority=NotificationPriority.HEARTBEAT,
            title=f"HEARTBEAT - AUTOBOT-{settings.ENVIRONMENT}",
            message="",
            metadata=system_state
        )
        return self.send_sync(notification)
    
    def reset_daily_latch(self):
        self._critical_latch.clear()
        self._save_latch_state()
        logger.info("CRITICAL latch reset")

notification_manager = TelegramNotificationManager()
