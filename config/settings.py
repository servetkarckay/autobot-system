"""
AUTOBOT System Configuration v1.2
Pydantic-based settings management with environment variable support

FIXES:
- Added cached secret values to avoid repeated get_secret_value() calls
- Added input validation
- Added security warnings for testnet credentials
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field, field_validator, model_validator
from typing import Literal, Optional
import logging

logger = logging.getLogger("autobot.config")


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # ============ Binance Configuration ============
    BINANCE_TESTNET: bool = True
    BINANCE_BASE_URL: str = "https://testnet.binancefuture.com"
    BINANCE_API_KEY: SecretStr
    BINANCE_API_SECRET: SecretStr
    BINANCE_USE_TESTNET: bool = True
    
    # Cached secret values (set after validation)
    _cached_api_key: Optional[str] = None
    _cached_api_secret: Optional[str] = None
    _cached_telegram_token: Optional[str] = None
    _cached_redis_password: Optional[str] = None
    
    # ============ Redis Configuration ============
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: SecretStr | None = None
    REDIS_DB: int = 0
    REDIS_STATE_TTL: int = 86400
    
    # ============ Telegram Configuration ============
    TELEGRAM_BOT_TOKEN: SecretStr
    TELEGRAM_CHAT_ID: str
    TELEGRAM_NOTIFICATIONS_ENABLED: bool = True
    
    # ============ System Configuration ============
    ENVIRONMENT: Literal["DRY_RUN", "TESTNET", "LIVE"] = "TESTNET"
    DRY_RUN: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: str = "json"
    
    # ============ Trading Parameters ============
    TRADING_SYMBOLS: list[str] = ["ZECUSDT"]
    MAX_POSITIONS: int = 1
    MAX_POSITION_SIZE_USDT: float = 1000.0
    LEVERAGE: int = 10
    ACCOUNT_EQUITY_USDT: float = 1000.0
    MAX_DRAWDOWN_PCT: float = 15.0
    DAILY_LOSS_LIMIT_PCT: float = 3.0
    
    # ============ Risk Parameters ============
    STOP_LOSS_ATR_MULTIPLIER: float = 2.5
    TRAILING_STOP_ATR_MULTIPLIER: float = 2.0
    ACTIVATION_THRESHOLD: float = 0.7
    CORRELATION_THRESHOLD: float = 0.8
    MAX_CORRELATION_EXPOSURE_PCT: float = 3.0
    
    # ============ Adaptive Parameters ============
    ADAPTIVE_TUNING_ENABLED: bool = True
    MIN_STRATEGY_WEIGHT: float = 0.5
    MAX_STRATEGY_WEIGHT: float = 1.5
    MIN_STOP_LOSS_MULTIPLIER: float = 2.0
    MAX_STOP_LOSS_MULTIPLIER: float = 4.0
    
    # Trailing Stop Settings
    TRAILING_STOP_ACTIVATION_PCT: float = 2.0  # Activate trailing at X% profit
    BREAK_EVEN_PCT: float = 2.0  # Move stop to entry at X% profit
    TRAILING_STOP_RATE: float = 0.5  # Move stop by X% per 1% additional profit
    
    PERFORMANCE_WINDOW_SIZE: int = 30
    
    # ============ Data Pipeline Configuration ============
    WEBSOCKET_RECONNECT_DELAY: int = 5
    WEBSOCKET_MAX_RECONNECT_ATTEMPTS: int = 10
    DATA_LOSS_TIMEOUT: int = 30
    
    # ============ Execution Configuration ============
    ORDER_TYPE_DEFAULT: Literal["MARKET", "LIMIT"] = "LIMIT"
    LIMIT_ORDER_EXPIRY_SECONDS: int = 10
    MAX_SLIPPAGE_PCT: float = 0.1
    MAX_SPED_ATR_PCT_RATIO: float = 0.1
    
    # ============ Metadata Engine Configuration ============
    METADATA_UPDATE_INTERVAL_HOURS: int = 24
    METADATA_VERSIONS_TO_KEEP: int = 5

    @model_validator(mode='after')
    def cache_secrets_and_validate(self) -> 'Settings':
        """Cache secret values and validate configuration"""
        # Cache secret values for performance
        self._cached_api_key = self.BINANCE_API_KEY.get_secret_value()
        self._cached_api_secret = self.BINANCE_API_SECRET.get_secret_value()
        self._cached_telegram_token = self.TELEGRAM_BOT_TOKEN.get_secret_value()
        self._cached_redis_password = self.REDIS_PASSWORD.get_secret_value() if self.REDIS_PASSWORD else None
        
        # Validate trading parameters
        if self.MAX_POSITIONS <= 0:
            raise ValueError("MAX_POSITIONS must be positive")
        if self.MAX_POSITION_SIZE_USDT <= 0:
            raise ValueError("MAX_POSITION_SIZE_USDT must be positive")
        if not (0 < self.MAX_DRAWDOWN_PCT <= 100):
            raise ValueError("MAX_DRAWDOWN_PCT must be between 0 and 100")
        if not (0 < self.DAILY_LOSS_LIMIT_PCT <= 50):
            raise ValueError("DAILY_LOSS_LIMIT_PCT must be between 0 and 50")
        
        # Security warning for testnet
        if self.BINANCE_TESTNET and self.ENVIRONMENT == "LIVE":
            logger.warning("SECURITY: Using TESTNET credentials in LIVE environment!")
        
        # Validate symbol list
        if not self.TRADING_SYMBOLS:
            raise ValueError("TRADING_SYMBOLS cannot be empty")
        
        return self
    
    @field_validator("BINANCE_BASE_URL")
    @classmethod
    def validate_binance_url(cls, v: str, info) -> str:
        if info.data.get("BINANCE_TESTNET", True):
            return "https://testnet.binancefuture.com"
        return "https://fapi.binance.com"
    
    # Cached property getters for performance
    @property
    def binance_api_key(self) -> str:
        """Get cached API key"""
        return self._cached_api_key or ""
    
    @property
    def binance_api_secret(self) -> str:
        """Get cached API secret"""
        return self._cached_api_secret or ""
    
    @property
    def telegram_bot_token(self) -> str:
        """Get cached Telegram token"""
        return self._cached_telegram_token or ""
    
    @property
    def redis_password(self) -> Optional[str]:
        """Get cached Redis password"""
        return self._cached_redis_password
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "LIVE"
    
    @property
    def is_testnet(self) -> bool:
        return self.BINANCE_TESTNET
    
    @property
    def is_dry_run(self) -> bool:
        if self.DRY_RUN:
            return True
        return self.ENVIRONMENT == "DRY_RUN"


def setup_logging():
    """Setup logging configuration"""
    import logging.config
    import json
    import sys
    from pathlib import Path
    
    settings_instance = Settings()
    
    log_level = getattr(logging, settings_instance.LOG_LEVEL)
    log_format = settings_instance.LOG_FORMAT
    
    if log_format == "json":
        logging.basicConfig(
            level=log_level,
            format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
    else:
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
    
    logger = logging.getLogger("autobot")
    logger.info(f"Logging initialized: level={settings_instance.LOG_LEVEL}, format={log_format}")
    return logger


# Global settings instance
settings = Settings()
logger = logging.getLogger("autobot.config")
