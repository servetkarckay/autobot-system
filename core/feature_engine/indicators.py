"""
AUTOBOT Feature Engine - Technical Indicators v1.3
Calculates technical indicators from OHLCV data

FIXES:
- Added comprehensive NaN/Infinity protection
- Added safe division operations
- Added input validation for all indicators
- Improved ADX calculation safety
"""
import logging
import math
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd

# pandas_ta temporarily disabled due to import issues
# try:
#     import pandas_ta as ta
# except ImportError:
#     ta = None
ta = None

logger = logging.getLogger("autobot.feature.indicators")


class IndicatorCalculator:
    """Calculates technical indicators with safety validations"""

    def __init__(self):
        self._cache: Dict[str, pd.DataFrame] = {}

    def _is_valid_numeric(self, value: float, allow_zero: bool = True, allow_negative: bool = True) -> bool:
        """Check if value is valid finite number"""
        try:
            return (
                isinstance(value, (int, float)) and
                math.isfinite(value) and
                not math.isnan(value) and
                (allow_zero or value != 0) and
                (allow_negative or value >= 0)
            )
        except (TypeError, ValueError):
            return False

    def _safe_divide(self, numerator: float, denominator: float, default: float = 0.0) -> float:
        """Safe division with zero-check"""
        try:
            if not self._is_valid_numeric(denominator, allow_zero=False) or math.isclose(denominator, 0, abs_tol=1e-10):
                return default
            result = numerator / denominator
            if not self._is_valid_numeric(result):
                return default
            return result
        except (ZeroDivisionError, ValueError, OverflowError):
            return default

    def _safe_series_to_float(self, series: pd.Series, default: float = 0.0) -> float:
        """Safely convert pandas Series to float"""
        try:
            if series is None or len(series) == 0:
                return default
            val = series.iloc[-1]
            if self._is_valid_numeric(val):
                return float(val)
            return default
        except (IndexError, TypeError, ValueError):
            return default

    def calculate_all(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate all technical indicators with safety checks"""
        if df is None or df.empty or len(df) < 55:
            logger.warning(f"Insufficient data: {len(df) if df is not None else 0} bars (need 55)")
            return {}

        indicators = {}

        try:
            # Validate required columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            missing_cols = [c for c in required_cols if c not in df.columns]
            if missing_cols:
                logger.error(f"Missing required columns: {missing_cols}")
                return {}

            # Clean data - remove NaN/Inf
            df_clean = df.replace([np.inf, -np.inf], np.nan).dropna(subset=required_cols)
            if len(df_clean) < 55:
                logger.warning(f"Insufficient clean data: {len(df_clean)} bars")
                return {}

            # TURTLE TRADING BREAKOUT LEVELS
            try:
                df_clean['high_20'] = df_clean['high'].rolling(window=20).max()
                df_clean['low_20'] = df_clean['low'].rolling(window=20).min()
                df_clean['high_55'] = df_clean['high'].rolling(window=55).max()
                df_clean['low_55'] = df_clean['low'].rolling(window=55).min()

                indicators["high_20"] = self._safe_series_to_float(df_clean['high_20'])
                indicators["low_20"] = self._safe_series_to_float(df_clean['low_20'])
                indicators["high_55"] = self._safe_series_to_float(df_clean['high_55'])
                indicators["low_55"] = self._safe_series_to_float(df_clean['low_55'])

                current_close = self._safe_series_to_float(df_clean['close'])
                indicators["breakout_20_long"] = current_close > indicators["high_20"]
                indicators["breakout_20_short"] = current_close < indicators["low_20"]
                indicators["breakout_55_long"] = current_close > indicators["high_55"]
                indicators["breakout_55_short"] = current_close < indicators["low_55"]
                indicators["close"] = current_close
            except Exception as e:
                logger.error(f"Error calculating breakout levels: {e}")
                indicators["high_20"] = indicators["low_20"] = 0.0
                indicators["high_55"] = indicators["low_55"] = 0.0
                indicators["close"] = 0.0

            # MOMENTUM INDICATORS
            indicators["rsi"] = self._calculate_rsi(df_clean["close"])
            indicators["stoch_k"], indicators["stoch_d"] = self._calculate_stochastic(df_clean)

            # TREND INDICATORS
            indicators["adx"] = self._calculate_adx(df_clean)
            indicators["ema_20"] = self._calculate_ema(df_clean["close"], 20)
            indicators["ema_50"] = self._calculate_ema(df_clean["close"], 50)
            indicators["ema_20_above_ema_50"] = indicators["ema_20"] > indicators["ema_50"]

            # VOLATILITY INDICATORS
            indicators["atr"] = self._calculate_atr(df_clean)
            indicators["atr_pct"] = self._safe_divide(indicators["atr"], indicators["close"], 0.0) * 100

            indicators["bb_upper"], indicators["bb_middle"], indicators["bb_lower"] = self._calculate_bollinger_bands(df_clean)
            if self._is_valid_numeric(indicators["bb_middle"], allow_zero=False):
                indicators["bb_width"] = self._safe_divide(
                    indicators["bb_upper"] - indicators["bb_lower"],
                    indicators["bb_middle"],
                    0.0
                ) * 100
            else:
                indicators["bb_width"] = 0.0

            # VOLUME INDICATORS
            indicators["volume_sma"] = self._safe_series_to_float(df_clean["volume"].rolling(window=20).mean())

            # Validate all indicators
            validated = {}
            for key, value in indicators.items():
                if isinstance(value, (int, float, np.number)):
                    validated[key] = float(value) if self._is_valid_numeric(value) else 0.0
                elif isinstance(value, bool):
                    validated[key] = value
                else:
                    validated[key] = value

            logger.debug(f"Calculated {len(validated)} indicators")
            return validated

        except Exception as e:
            logger.error(f"Error in calculate_all: {e}", exc_info=True)
            return {}

    def _calculate_rsi(self, close: pd.Series, period: int = 14) -> float:
        """Calculate RSI with safety checks"""
        try:
            if ta is not None:
                rsi_series = ta.rsi(close, length=period)
                return self._safe_series_to_float(rsi_series, default=50.0)

            # Fallback calculation
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = self._safe_divide(gain, loss, default=1.0)
            rsi = 100 - self._safe_divide(100, 1 + rs, default=50.0)
            return self._safe_series_to_float(rsi, default=50.0)
        except Exception as e:
            logger.error(f"RSI calculation error: {e}")
            return 50.0

    def _calculate_stochastic(self, df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> tuple:
        """Calculate Stochastic with safety checks"""
        try:
            # Validate input type
            if not isinstance(df, pd.DataFrame):
                return 50.0, 50.0
            
            if df.empty or len(df) < k_period:
                return 50.0, 50.0
                
            low_min = df["low"].rolling(window=k_period).min()
            high_max = df["high"].rolling(window=k_period).max()

            range_val = high_max - low_min
            k = self._safe_divide(
                100 * (df["close"] - low_min),
                range_val,
                default=50.0
            )
            d = k.rolling(window=d_period).mean()
            return self._safe_series_to_float(k, default=50.0), self._safe_series_to_float(d, default=50.0)
        except Exception as e:
            logger.error(f"Stochastic calculation error: {e}")
            return 50.0, 50.0

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ADX with comprehensive safety checks"""
        try:
            # Validate input type
            if not isinstance(df, pd.DataFrame):
                return 20.0
            
            if df.empty or len(df) < period + 1:
                return 20.0
            
            # Clean input data
            high = df["high"].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
            low = df["low"].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
            close = df["close"].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

            if ta is not None:
                try:
                    adx_series = ta.adx(high, low, close, length=period)["ADX_14"]
                    adx_val = self._safe_series_to_float(adx_series, default=0.0)
                    if 0 <= adx_val <= 100:
                        return adx_val
                except Exception as e:
                    logger.debug(f"pandas-ta ADX failed, using fallback: {e}")

            # Fallback calculation with comprehensive safety
            plus_dm = high.diff()
            minus_dm = -low.diff()
            plus_dm = plus_dm.where(plus_dm > 0, 0)
            minus_dm = minus_dm.where(minus_dm > 0, 0)

            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)

            atr = tr.rolling(window=period).mean()

            # Safe division for DI calculation
            atr_safe = atr.replace(0, np.nan)
            plus_di = self._safe_divide(
                100 * plus_dm.rolling(window=period).mean(),
                atr_safe,
                default=0.0
            )
            minus_di = self._safe_divide(
                100 * minus_dm.rolling(window=period).mean(),
                atr_safe,
                default=0.0
            )

            # Safe DX calculation
            di_sum = plus_di + minus_di
            di_sum_safe = di_sum.replace(0, np.nan)
            dx = self._safe_divide(
                100 * (plus_di - minus_di).abs(),
                di_sum_safe,
                default=0.0
            )

            adx = dx.rolling(window=period).mean()
            adx_val = self._safe_series_to_float(adx, default=20.0)

            # Final validation
            if not self._is_valid_numeric(adx_val) or adx_val < 0 or adx_val > 100:
                logger.warning(f"Invalid ADX calculated: {adx_val}, defaulting to 20")
                return 20.0

            return min(adx_val, 100.0)

        except Exception as e:
            logger.error(f"ADX calculation error: {e}")
            return 20.0

    def _calculate_ema(self, close: pd.Series, period: int) -> float:
        """Calculate EMA with safety checks"""
        try:
            ema = close.ewm(span=period, adjust=False).mean()
            return self._safe_series_to_float(ema, default=0.0)
        except Exception as e:
            logger.error(f"EMA calculation error: {e}")
            return 0.0

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ATR with safety checks"""
        try:
            high_low = df["high"] - df["low"]
            high_close = (df["high"] - df["close"].shift()).abs()
            low_close = (df["low"] - df["close"].shift()).abs()

            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean()
            val = self._safe_series_to_float(atr, default=0.0)
            return max(val, 0.0) if self._is_valid_numeric(val) else 0.0
        except Exception as e:
            logger.error(f"ATR calculation error: {e}")
            return 0.0

    def _calculate_bollinger_bands(self, df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> tuple:
        """Calculate Bollinger Bands with safety checks"""
        try:
            sma = df["close"].rolling(window=period).mean()
            std = df["close"].rolling(window=period).std()

            upper = sma + (std * std_dev)
            lower = sma - (std * std_dev)

            return (
                self._safe_series_to_float(upper, default=0.0),
                self._safe_series_to_float(sma, default=0.0),
                self._safe_series_to_float(lower, default=0.0)
            )
        except Exception as e:
            logger.error(f"Bollinger Bands calculation error: {e}")
            return 0.0, 0.0, 0.0
