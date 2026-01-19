"""
AUTOBOT Notification Manager - Telegram Integration
Priority-based notification system with async queue
"""
import logging
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json

try:
    import telegram
    from telegram import Bot, ParseMode
    from telegram.error import TelegramError
except ImportError:
    telegram = None
    Bot = None

from config.settings import settings

logger = logging.getLogger("autobot.notification.telegram")


class NotificationPriority(Enum):
    """Notification priority levels"""
    CRITICAL = "CRITICAL"  # 🔴 Immediate human intervention required
    ERROR = "ERROR"        # 🟠 System error, auto-recovery attempted
    WARNING = "WARNING"    # 🟡 Potential risk or anomaly
    INFO = "INFO"          # 🔵 Routine operational information
    HEARTBEAT = "HEARTBEAT" # 🟢 System health status


@dataclass
class NotificationMessage:
    """Structured notification message"""
    priority: NotificationPriority
    title: str
    message: str
    metadata: Dict[str, Any]
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def format(self) -> str:
        """Format message for Telegram"""
        emoji = {
            NotificationPriority.CRITICAL: "🔴",
            NotificationPriority.ERROR: "🟠",
            NotificationPriority.WARNING: "🟡",
            NotificationPriority.INFO: "🔵",
            NotificationPriority.HEARTBEAT: "🟢",
        }
        
        lines = [
            f"{emoji.get(self.priority, )} {self.title}",
            f"*Timestamp (UTC):* {self.timestamp.strftime(%Y-%m-%d %H:%M:%S)}",
        ]
        
        # Add metadata
        if self.metadata:
            lines.append("")
            for key, value in self.metadata.items():
                lines.append(f"*{key}:* {value}")
        
        lines.append("")
        lines.append(self.message)
        
        return "\n".join(lines)


class TelegramNotificationManager:
    """Manages Telegram notifications with priority queuing"""
    
    def __init__(self):
        self._bot: Optional[Bot] = None
        self._chat_id: Optional[str] = None
        self._enabled = settings.TELEGRAM_NOTIFICATIONS_ENABLED
        self._message_queue: asyncio.Queue = None
        self._worker_task: asyncio.Task = None
        
        if self._enabled and telegram is not None:
            self._initialize_bot()
    
    def _initialize_bot(self):
        """Initialize Telegram bot"""
        try:
            token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
            self._bot = Bot(token=token)
            self._chat_id = settings.TELEGRAM_CHAT_ID
            logger.info("Telegram bot initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            self._enabled = False
    
    async def send(self, notification: NotificationMessage) -> bool:
        """Send a notification (async)"""
        
        if not self._enabled or self._bot is None:
            # Log locally if Telegram not available
            self._log_notification(notification)
            return False
        
        try:
            message = notification.format()
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.debug(f"Notification sent: {notification.title}")
            return True
        except TelegramError as e:
            logger.error(f"Telegram send failed: {e}")
            self._log_notification(notification)
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending notification: {e}")
            return False
    
    def send_sync(self, notification: NotificationMessage) -> bool:
        """Send a notification (synchronous wrapper)"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.send(notification))
    
    def _log_notification(self, notification: NotificationMessage):
        """Log notification locally if Telegram unavailable"""
        log_level = {
            NotificationPriority.CRITICAL: logging.CRITICAL,
            NotificationPriority.ERROR: logging.ERROR,
            NotificationPriority.WARNING: logging.WARNING,
            NotificationPriority.INFO: logging.INFO,
            NotificationPriority.HEARTBEAT: logging.INFO,
        }
        
        logger.log(
            log_level.get(notification.priority, logging.INFO),
            f"[{notification.priority.value}] {notification.title}: {notification.message}"
        )
    
    # Convenience methods for common notifications
    
    def send_critical(self, title: str, message: str, **metadata):
        """Send CRITICAL priority notification"""
        notification = NotificationMessage(
            priority=NotificationPriority.CRITICAL,
            title=f"CRITICAL ALERT - {title}",
            message=message,
            metadata=metadata
        )
        return self.send_sync(notification)
    
    def send_error(self, title: str, message: str, **metadata):
        """Send ERROR priority notification"""
        notification = NotificationMessage(
            priority=NotificationPriority.ERROR,
            title=f"SYSTEM ERROR - {title}",
            message=message,
            metadata=metadata
        )
        return self.send_sync(notification)
    
    def send_warning(self, title: str, message: str, **metadata):
        """Send WARNING priority notification"""
        notification = NotificationMessage(
            priority=NotificationPriority.WARNING,
            title=f"WARNING - {title}",
            message=message,
            metadata=metadata
        )
        return self.send_sync(notification)
    
    def send_info(self, title: str, message: str, **metadata):
        """Send INFO priority notification"""
        notification = NotificationMessage(
            priority=NotificationPriority.INFO,
            title=title,
            message=message,
            metadata=metadata
        )
        return self.send_sync(notification)
    
    def send_heartbeat(self, system_state: Dict):
        """Send HEARTBEAT status update"""
        notification = NotificationMessage(
            priority=NotificationPriority.HEARTBEAT,
            title=f"DAILY SUMMARY - AUTOBOT-{settings.ENVIRONMENT}",
            message="",
            metadata=system_state
        )
        return self.send_sync(notification)


# Global notification manager instance
notification_manager = TelegramNotificationManager()
