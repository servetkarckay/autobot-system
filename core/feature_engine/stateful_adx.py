"""
Stateful ADX Calculator - Incremental ADX calculation for real-time updates
"""
import logging
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger("autobot.feature.indicators")


class StatefulADX:
    """Incremental ADX calculator - maintains state for incremental updates"""
    
    def __init__(self, period: int = 14):
        self.period = period
        self._prev_close: Optional[float] = None
        self._prev_atr: Optional[float] = None
        self._prev_plus_di: Optional[float] = None
        self._prev_minus_di: Optional[float] = None
        self._adx: Optional[float] = None
        self._is_seeded = False
    
    def seed(self, df: pd.DataFrame):
        """Seed with historical data"""
        if df is None or len(df) < self.period + 1:
            logger.warning(f"[ADX] Not enough data: {len(df) if df is not None else 0} bars")
            return
        
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        
        # Calculate ADX properly
        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        atr = tr[self.period:].mean()
        
        diff = high[1:] - low[:-1]
        plus_dm = np.where(diff > 0, diff, 0.0)
        minus_dm = np.where(diff < 0, -diff, 0.0)
        
        self._prev_plus_dm = plus_dm[-period:].mean()
        self._prev_minus_dm = minus_dm[-period:].mean()
        
        plus_di = 100 * self._prev_plus_dm / atr if atr > 0 else 0
        minus_di = 100 * self._prev_minus_dm / atr if atr > 0 else 0
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
        
        # Smooth ADX over period
        dx_values = []
        for i in range(len(df) - self.period - 1, len(df)):
            if i >= 0:
                # Calculate DX at this point
                idx = i
                if idx >= self.period:
                    recent_plus_dm = plus_dm[max(0, idx-self.period):idx+1].mean()
                    recent_minus_dm = minus_dm[max(0, idx-self.period):idx+1].mean()
                    recent_atr = tr[max(0, idx-self.period):idx+1].mean()
                    recent_plus_di = 100 * recent_plus_dm / recent_atr if recent_atr > 0 else 0
                    recent_minus_di = 100 * recent_minus_dm / recent_atr if recent_atr > 0 else 0
                    dx_val = 100 * abs(recent_plus_di - recent_minus_di) / (recent_plus_di + recent_minus_di) if (recent_plus_di + recent_minus_di) > 0 else 0
                    dx_values.append(dx_val)
        
        if len(dx_values) >= self.period:
            self._adx = dx_values[-self.period:].mean()
        else:
            self._adx = 20.0
        
        self._prev_close = close[-1]
        self._is_seeded = True
        logger.debug(f"[ADX SEED] {self._adx:.1f}")
    
    def update(self, high: float, low: float, close: float) -> float:
        """Update with new candle"""
        if not self._is_seeded:
            return 20.0
        
        try:
            # Simple incremental update - recalculate from last period+1 bars
            # Store data and recalculate
            if not hasattr(self, '_data_high'):
                self._data_high = []
                self._data_low = []
                self._data_close = []
            
            self._data_high.append(high)
            self._data_low.append(low)
            self._data_close.append(close)
            
            # Keep only period + 50 data points
            if len(self._data_high) > self.period + 50:
                self._data_high = self._data_high[-(self.period + 50):]
                self._data_low = self._data_low[-(self.period + 50):]
                self._data_close = self._data_close[-(self.period + 50):]
            
            # Recalculate ADX from stored data
            if len(self._data_high) >= self.period + 1:
                high_arr = np.array(self._data_high)
                low_arr = np.array(self._data_low)
                close_arr = np.array(self._data_close)
                
                # TR
                tr1 = high_arr - low_arr
                tr2 = np.abs(high_arr - np.roll(close_arr, 1))
                tr3 = np.abs(low_arr - np.roll(close_arr, 1))
                tr = np.maximum(tr1, np.maximum(tr2, tr3))
                atr = tr[-self.period:].mean()
                
                # DM
                diff = high_arr[1:] - low_arr[:-1]
                plus_dm = np.where(diff > 0, diff, 0.0)
                minus_dm = np.where(diff < 0, -diff, 0.0)
                
                plus_di = 100 * plus_dm[-self.period:].mean() / atr if atr > 0 else 0
                minus_di = 100 * minus_dm[-self.period:].mean() / atr if atr > 0 else 0
                
                dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
                
                # Update ADX smoothing
                if self._adx is None:
                    self._adx = dx
                else:
                    alpha = 1.0 / self.period
                    self._adx = alpha * dx + (1 - alpha) * self._adx
                
                return max(0, min(100, self._adx))
            
            return self._adx if self._adx is not None else 20.0
            
        except Exception as e:
            logger.error(f"[ADX UPDATE] Error: {e}")
            return 20.0
    
    def get_adx(self) -> float:
        return self._adx if self._adx is not None else 20.0
    
    def is_seeded(self) -> bool:
        return self._is_seeded
