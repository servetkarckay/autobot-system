"""
AUTOBOT Common Validation Helpers v1.0
Centralized input validation and safety utilities for all modules
"""
import math
import re
from typing import Any, Optional, List
from decimal import Decimal, InvalidOperation
import logging

logger = logging.getLogger("autobot.utils.validation")


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


class ValidationHelpers:
    """Centralized validation utilities"""
    
    # Trading pair pattern (e.g., BTCUSDT, ETHUSDT, PEPEUSDT)
    TRADING_PAIR_PATTERN = re.compile(r'^[A-Z]{2,20}USDT$')
    
    # Minimum and maximum values for trading parameters
    MIN_PRICE = 1e-15  # Minimum valid price
    MAX_PRICE = 1e15   # Maximum valid price
    MIN_QUANTITY = 1e-15
    MAX_QUANTITY = 1e15
    
    @staticmethod
    def is_valid_numeric(value: Any, allow_zero: bool = True, allow_negative: bool = True, 
                       min_val: Optional[float] = None, max_val: Optional[float] = None) -> bool:
        """
        Check if value is a valid finite number within optional bounds
        
        Args:
            value: Value to check
            allow_zero: Whether zero is allowed
            allow_negative: Whether negative numbers are allowed
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
        
        Returns:
            True if value is valid
        """
        try:
            # Type check
            if not isinstance(value, (int, float, Decimal)):
                return False
            
            # Convert to float for comparison
            num_val = float(value)
            
            # NaN/Inf check
            if not math.isfinite(num_val):
                return False
            
            # Zero check
            if not allow_zero and abs(num_val) < 1e-10:
                return False
            
            # Negative check
            if not allow_negative and num_val < 0:
                return False
            
            # Range checks
            if min_val is not None and num_val < min_val:
                return False
            if max_val is not None and num_val > max_val:
                return False
            
            return True
        except (TypeError, ValueError, OverflowError):
            return False
    
    @staticmethod
    def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
        """
        Safe division with zero-check and NaN protection
        
        Args:
            numerator: Numerator value
            denominator: Denominator value
            default: Default value if division fails
        
        Returns:
            Division result or default value
        """
        try:
            if not ValidationHelpers.is_valid_numeric(denominator, allow_zero=False):
                return default
            result = numerator / denominator
            if not ValidationHelpers.is_valid_numeric(result):
                return default
            return result
        except (ZeroDivisionError, ValueError, OverflowError):
            return default
    
    @staticmethod
    def safe_percentage(value: float, total: float, default: float = 0.0) -> float:
        """Calculate safe percentage with zero-check"""
        if not ValidationHelpers.is_valid_numeric(total, allow_zero=False):
            return default
        return ValidationHelpers.safe_divide(value * 100, total, default)
    
    @staticmethod
    def validate_trading_pair(symbol: str) -> bool:
        """Validate trading pair symbol format"""
        if not isinstance(symbol, str):
            return False
        return bool(ValidationHelpers.TRADING_PAIR_PATTERN.match(symbol))
    
    @staticmethod
    def validate_price(price: float) -> bool:
        """Validate price is within acceptable range"""
        return ValidationHelpers.is_valid_numeric(
            price, 
            allow_zero=False, 
            allow_negative=False,
            min_val=ValidationHelpers.MIN_PRICE,
            max_val=ValidationHelpers.MAX_PRICE
        )
    
    @staticmethod
    def validate_quantity(quantity: float) -> bool:
        """Validate quantity is within acceptable range"""
        return ValidationHelpers.is_valid_numeric(
            quantity,
            allow_zero=False,
            allow_negative=False,
            min_val=ValidationHelpers.MIN_QUANTITY,
            max_val=ValidationHelpers.MAX_QUANTITY
        )
    
    @staticmethod
    def validate_percentage(value: float, min_val: float = 0.0, max_val: float = 100.0) -> bool:
        """Validate percentage is within 0-100 range or custom bounds"""
        return ValidationHelpers.is_valid_numeric(
            value,
            allow_zero=True,
            allow_negative=False,
            min_val=min_val,
            max_val=max_val
        )
    
    @staticmethod
    def validate_bounding_box(value: float, min_val: float, max_val: float, 
                            default: Optional[float] = None) -> float:
        """
        Ensure value is within bounds, return default or clamped value if not
        
        Args:
            value: Value to check
            min_val: Minimum allowed value
            max_val: Maximum allowed value
            default: Default value if out of bounds (None = clamp)
        
        Returns:
            Value within bounds
        """
        if not ValidationHelpers.is_valid_numeric(value):
            if default is not None:
                return default
            raise ValidationError(f"Invalid numeric value: {value}")
        
        if value < min_val:
            if default is not None:
                return default
            return min_val
        if value > max_val:
            if default is not None:
                return default
            return max_val
        return value
    
    @staticmethod
    def sanitize_string(value: Any, max_length: int = 1000, 
                      allow_empty: bool = False) -> Optional[str]:
        """
        Sanitize string input
        
        Args:
            value: Input value
            max_length: Maximum allowed length
            allow_empty: Whether empty strings are allowed
        
        Returns:
            Sanitized string or None
        """
        if value is None:
            return None
        
        str_val = str(value).strip()
        
        if not str_val and not allow_empty:
            return None
        
        if len(str_val) > max_length:
            str_val = str_val[:max_length]
        
        return str_val
    
    @staticmethod
    def validate_list_length(items: List, min_length: int = 0, 
                           max_length: int = 10000) -> bool:
        """Validate list length is within bounds"""
        return min_length <= len(items) <= max_length
    
    @staticmethod
    def safe_float_conversion(value: Any, default: float = 0.0) -> float:
        """Safely convert value to float"""
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return default
    
    @staticmethod
    def validate_api_key(key: str) -> bool:
        """Basic API key format validation"""
        if not isinstance(key, str):
            return False
        # API keys are typically 32-128 alphanumeric characters
        return 32 <= len(key) <= 128 and key.isalnum()
    
    @staticmethod
    def validate_telegram_token(token: str) -> bool:
        """Validate Telegram bot token format (e.g., 123456789:ABCdefGHIjklMNOpqrsTUVwxyz)"""
        if not isinstance(token, str):
            return False
        pattern = re.compile(r'^\d+:[A-Za-z0-9_-]{35}$')
        return bool(pattern.match(token))
    
    @staticmethod
    def validate_chat_id(chat_id: str) -> bool:
        """Validate Telegram chat ID (can be negative for groups)"""
        try:
            int(chat_id)
            return True
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp value between min and max"""
        return max(min_val, min(max_val, value))


# Global instance for easy import
validate = ValidationHelpers
