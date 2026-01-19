"""
AUTOBOT Logging Configuration
Structured JSON logging for production environments
"""
import os
import logging
import sys
import json
from datetime import datetime
from typing import Any, Dict

from pythonjsonlogger import jsonlogger

from config.settings import settings


class JsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields"""
    
    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]):
        super().add_fields(log_record, record, message_dict)
        
        # Add custom fields
        log_record["timestamp"] = datetime.utcnow().isoformat() + "Z"
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["module"] = record.module
        log_record["function"] = record.funcName
        log_record["line"] = record.lineno
        
        # Add system info
        log_record["system"] = "AUTOBOT"
        log_record["environment"] = settings.ENVIRONMENT


def setup_logging(name: str = "autobot") -> logging.Logger:
    """Set up structured logging for the application"""
    
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    
    if settings.LOG_FORMAT == "json":
        formatter = JsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s",
            timestamp=True
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (always in JSON format for parsing)
    os.makedirs("logs", exist_ok=True)
    file_handler = logging.FileHandler("logs/autobot.log")
    file_formatter = JsonFormatter(
        "%(timestamp)s %(level)s %(logger)s %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    return logger


# Module-level logger
logger = setup_logging("autobot")
