"""
AUTOBOT Feature Engine - Technical Indicators
Calculates technical indicators from OHLCV data
"""
import logging
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
except ImportError:
    ta = None

logger = logging.getLogger("autobot.feature.indicators")


class IndicatorCalculator:
    """Calculates technical indicators for trading signals"""
    
    def __init__(self):
        self._cache: Dict[str, pd.DataFrame] = {}
    
    def calculate_all(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calculate all technical indicators for a DataFrame.
        
        Args:
            df: DataFrame with OHLCV columns (open, high, low, close, volume)
        
        Returns:
            Dictionary of indicator values
        """
        
        if df.empty or len(df) < 55:
            logger.warning(f"Insufficient data for indicator calculation: {len(df)} bars (need 55 for breakout)")
            return {}
        
        indicators = {}
        
        try:
            # ============================================================
            # TURTLE TRADING BREAKOUT LEVELS
            # ============================================================
            
            # 20-day high/low (short-term breakout)
            df['high_20'] = df['high'].rolling(window=20).max()
            df['low_20'] = df['low'].rolling(window=20).min()
            
            # 55-day high/low (long-term breakout)
            df['high_55'] = df['high'].rolling(window=55).max()
            df['low_55'] = df['low'].rolling(window=55).min()
            
            # Get latest breakout levels
            indicators["high_20"] = float(df['high_20'].iloc[-1])
            indicators["low_20"] = float(df['low_20'].iloc[-1])
            indicators["high_55"] = float(df['high_55'].iloc[-1])
            indicators["low_55"] = float(df['low_55'].iloc[-1])
            
            # Breakout signals (flags)
            current_close = float(df['close'].iloc[-1])
            indicators["breakout_20_long"] = current_close > indicators["high_20"]
            indicators["breakout_20_short"] = current_close < indicators["low_20"]
            indicators["breakout_55_long"] = current_close > indicators["high_55"]
            indicators["breakout_55_short"] = current_close < indicators["low_55"]
            
            # ============================================================
            # MOMENTUM INDICATORS
            # ============================================================
            
            # RSI
            indicators["rsi"] = self._calculate_rsi(df["close"])
            
            # Stochastic
            indicators["stoch_k"], indicators["stoch_d"] = self._calculate_stochastic(df)
            
            # ============================================================
            # TREND INDICATORS
            # ============================================================
            
            # ADX (trend strength)
            indicators["adx"] = self._calculate_adx(df)
            
            # EMAs
            indicators["ema_20"] = self._calculate_ema(df["close"], 20)
            indicators["ema_50"] = self._calculate_ema(df["close"], 50)
            indicators["ema_20_above_ema_50"] = indicators["ema_20"] > indicators["ema_50"]
            
            # ============================================================
            # VOLATILITY INDICATORS
            # ============================================================
            
            # ATR (for Turtle position sizing)
            indicators["atr"] = self._calculate_atr(df)
            indicators["atr_pct"] = indicators["atr"] / df["close"].iloc[-1] * 100
            
            # Bollinger Bands
            indicators["bb_upper"], indicators["bb_middle"], indicators["bb_lower"] = self._calculate_bollinger_bands(df)
            indicators["bb_width"] = (indicators["bb_upper"] - indicators["bb_lower"]) / indicators["bb_middle"] * 100
            
            # ============================================================
            # VOLUME INDICATORS
            # ============================================================
            
            indicators["volume_sma"] = df["volume"].rolling(window=20).mean().iloc[-1]
            
            # Current price
            indicators["close"] = float(df['close'].iloc[-1])
            
            # Latest values
            latest = {}
            for key, value in indicators.items():
                if isinstance(value, (int, float, np.number)):
                    latest[key] = float(value)
                elif isinstance(value, pd.Series):
                    latest[key] = float(value.iloc[-1]) if len(value) > 0 else None
                elif isinstance(value, (list, tuple)):
                    latest[key] = [float(v.iloc[-1]) if isinstance(v, pd.Series) and len(v) > 0 else None for v in value]
                else:
                    latest[key] = value
            
            logger.debug(f"Calculated {len(latest)} indicators (including breakout levels)")
            return latest
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return {}
    
    def _calculate_rsi(self, close: pd.Series, period: int = 14) -> float:
        """Calculate RSI indicator"""
        if ta is not None:
            rsi_series = ta.rsi(close, length=period)
            return float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else 50.0
        
        # Fallback calculation
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if len(rsi) > 0 else 50.0
    
    def _calculate_stochastic(self, df: pd.DataFrame, k_period: int = 14, 
                             d_period: int = 3) -> tuple:
        """Calculate Stochastic oscillator"""
        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()
        
        k = 100 * (df["close"] - low_min) / (high_max - low_min)
        d = k.rolling(window=d_period).mean()
        
        return float(k.iloc[-1]) if len(k) > 0 else 50.0, float(d.iloc[-1]) if len(d) > 0 else 50.0
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ADX indicator"""
        if ta is not None:
            adx_series = ta.adx(df["high"], df["low"], df["close"], length=period)["ADX_14"]
            return float(adx_series.iloc[-1]) if len(adx_series) > 0 else 0.0
        
        # Simplified ADX calculation
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return float(adx.iloc[-1]) if len(adx) > 0 else 0.0
    
    def _calculate_ema(self, close: pd.Series, period: int) -> float:
        """Calculate EMA indicator"""
        ema = close.ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1]) if len(ema) > 0 else 0.0
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ATR indicator"""
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return float(atr.iloc[-1]) if len(atr) > 0 else 0.0
    
    def _calculate_bollinger_bands(self, df: pd.DataFrame, period: int = 20, 
                                  std_dev: float = 2.0) -> tuple:
        """Calculate Bollinger Bands"""
        sma = df["close"].rolling(window=period).mean()
        std = df["close"].rolling(window=period).std()
        
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        
        return float(upper.iloc[-1]), float(sma.iloc[-1]), float(lower.iloc[-1])
