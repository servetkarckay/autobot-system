"""
AUTOBOT System Configuration
Pydantic-based settings management with environment variable support
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field, field_validator
from typing import Literal


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
    BINANCE_USE_TESTNET: bool = True  # For backward compatibility
    
    # ============ Redis Configuration ============
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: SecretStr | None = None
    REDIS_DB: int = 0
    REDIS_STATE_TTL: int = 86400  # 24 hours
    
    # ============ Telegram Configuration ============
    TELEGRAM_BOT_TOKEN: SecretStr
    TELEGRAM_CHAT_ID: str
    TELEGRAM_NOTIFICATIONS_ENABLED: bool = True
    
    # ============ System Configuration ============
    ENVIRONMENT: Literal["DRY_RUN", "TESTNET", "LIVE"] = "DRY_RUN"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "text"
    
    # ============ Trading Parameters ============
    MAX_POSITIONS: int = 5
    MAX_POSITION_SIZE_USDT: float = 1000.0
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
    PERFORMANCE_WINDOW_SIZE: int = 30  # trades
    
    # ============ Data Pipeline Configuration ============
    WEBSOCKET_RECONNECT_DELAY: int = 5
    WEBSOCKET_MAX_RECONNECT_ATTEMPTS: int = 10
    DATA_LOSS_TIMEOUT: int = 30  # seconds
    
    # ============ Execution Configuration ============
    ORDER_TYPE_DEFAULT: Literal["MARKET", "LIMIT"] = "LIMIT"
    LIMIT_ORDER_EXPIRY_SECONDS: int = 10
    MAX_SLIPPAGE_PCT: float = 0.1
    MAX_SPED_ATR_PCT_RATIO: float = 0.1
    
    # ============ Metadata Engine Configuration ============
    METADATA_UPDATE_INTERVAL_HOURS: int = 24
    METADATA_VERSIONS_TO_KEEP: int = 5
    
    @field_validator("BINANCE_BASE_URL")
    @classmethod
    def validate_binance_url(cls, v: str, info) -> str:
        if info.data.get("BINANCE_TESTNET", True):
            return "https://testnet.binancefuture.com"
        return "https://fapi.binance.com"
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "LIVE"
    
    @property
    def is_testnet(self) -> bool:
        return self.BINANCE_TESTNET
    
    @property
    def is_dry_run(self) -> bool:
        return self.ENVIRONMENT == "DRY_RUN"


# Global settings instance
settings = Settings()
