"""
AUTOBOT Notification Manager - PRODUCTION READY
Fixed event loop conflict for async environments
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
import concurrent.futures

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

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape special HTML characters"""
        if not isinstance(text, str):
            return str(text)
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;"))

    def format(self) -> str:
        # Format using HTML tags (more reliable than Markdown)
        title_escaped = self._escape_html(self.title)
        message_escaped = self._escape_html(self.message)

        lines = [
            f"🔔 <b>{title_escaped}</b>",
            f"📅 {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        ]

        if self.metadata:
            lines.append("\n📊 <b>Details:</b>")
            for key, value in sorted(self.metadata.items()):
                if value is not None:
                    key_escaped = self._escape_html(str(key))
                    value_escaped = self._escape_html(str(value))
                    lines.append(f"  • {key_escaped}: {value_escaped}")

        lines.append(f"\n💬 {message_escaped}")
        return "\n".join(lines)
    
    def get_event_key(self) -> str:
        key_parts = [self.title]
        if self.metadata:
            for k, v in sorted(self.metadata.items()):
                key_parts.append(f"{k}={v}")
        return ":".join(key_parts)

class TelegramNotificationManager:
    _instance = None
    _lock = Lock()
    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="telegram")
    
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
        with TelegramNotificationManager._lock:
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
            await self._bot.send_message(chat_id=self._chat_id, text=message, parse_mode='HTML')
            logger.info(f"[TELEGRAM SENT] [{notification.priority.value}] {notification.title}")
            return True
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            self._log_notification(notification)
            return False
    
    def _run_in_thread(self, notification: NotificationMessage) -> bool:
        """Run async send in a separate thread - FIXED with per-thread bot"""
        from telegram import Bot
        from config.settings import settings
        
        bot = None
        try:
            token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
            chat_id = settings.TELEGRAM_CHAT_ID
            
            # Create new bot for this thread (avoids event loop conflicts)
            bot = Bot(token=token)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def send_with_timeout():
                    try:
                        msg = notification.format()
                        await bot.send_message(
                            chat_id=chat_id, 
                            text=msg, 
                            parse_mode='HTML',
                            read_timeout=10,
                            write_timeout=10,
                            connect_timeout=10
                        )
                        return True
                    except Exception as e:
                        raise e
                
                result = loop.run_until_complete(send_with_timeout())
                if result:
                    logger.info(f"[TELEGRAM SENT] [{notification.priority.value}] {notification.title}")
                return result
            except Exception as e:
                logger.error(f"Telegram send error in thread: {type(e).__name__}: {e}")
                return False
            finally:
                # Clean up pending tasks
                try:
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()
        except Exception as e:
            logger.error(f"Thread execution error: {type(e).__name__}: {e}")
            self._log_notification(notification)
            return False
        finally:
            # Shutdown bot properly
            if bot is not None:
                try:
                    # Bot needs async shutdown
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(bot.shutdown())
                    finally:
                        loop.close()
                except Exception:
                    pass
    
    def send_sync(self, notification: NotificationMessage) -> bool:
        if notification.priority == NotificationPriority.CRITICAL:
            event_key = notification.get_event_key()
            if self._check_latch(event_key):
                logger.warning(f"CRITICAL latched: {event_key}")
                return False
        
        if not self._check_rate_limit(notification.priority):
            logger.debug(f"Rate limited: {notification.priority.value}")
            return False
        
        try:
            # Check if we're in an async context
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, submit to thread pool
                future = self._executor.submit(self._run_in_thread, notification)
                result = future.result(timeout=12.0)
                if result:
                    with TelegramNotificationManager._lock:
                        self._send_history[notification.priority.value].append(time.time())
                    if notification.priority == NotificationPriority.CRITICAL:
                        self._set_latch(notification.get_event_key())
                return result
            except RuntimeError:
                # No running loop, use direct execution
                return self._run_in_thread(notification)
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
    
    def shutdown(self):
        """Cleanup on shutdown"""
        self._executor.shutdown(wait=True)

notification_manager = TelegramNotificationManager()
