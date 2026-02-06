# ADX Fix Script - Fixes the incremental buffer issue

import re

# Read the file
with open('/root/autobot_system/core/data_pipeline/event_engine.py', 'r') as f:
    content = f.read()

# Find the problematic section and fix it
# We need to ensure the DataFrame has enough data before calculating ADX

# Replace the problematic code section
old_code = '''            # Use the new calculator
            features = self.indicator_calculator.calculate_features(
                symbol,
                new_price=price,
                full_data=df  # Provide the full dataframe for non-incremental indicators
            )
            
            # Use safe IndicatorCalculator (replaces unreliable pandas_ta)
            safe_calc = IndicatorCalculator()
            safe_features = safe_calc.calculate_all(df)'''

new_code = '''            # Store full historical data for proper ADX calculation
            # Store in historical buffer if not exists
            if not hasattr(self, '_historical_df'):
                self._historical_df = {}
            
            # Only update historical data periodically (every 10th kline) to save memory
            if symbol not in self._historical_df or trigger == 'kline_close':
                # Use incremental data but keep historical
                if symbol not in self._historical_df:
                    self._historical_df[symbol] = df.copy()
                else:
                    # Append new data to historical
                    last_ts = self._historical_df[symbol].iloc[-1]['timestamp'] if len(self._historical_df[symbol]) > 0 else 0
                    new_ts = df.iloc[-1]['timestamp'] if hasattr(df.iloc[-1], 'timestamp') else 0
                    
                    # Only append if it's a new candle
                    if new_ts > last_ts:
                        self._historical_df[symbol] = pd.concat([self._historical_df[symbol], df], ignore_index=True)
            
            # Use the new calculator
            features = self.indicator_calculator.calculate_features(
                symbol,
                new_price=price,
                full_data=df  # Provide the full dataframe for non-incremental indicators
            )
            
            # Use safe IndicatorCalculator with HISTORICAL data for proper ADX
            safe_calc = IndicatorCalculator()
            historical_df = self._historical_df.get(symbol, df)
            safe_features = safe_calc.calculate_all(historical_df)'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open('/root/autobot_system/core/data_pipeline/event_engine.py', 'w') as f:
        f.write(content)
    print('FIX APPLIED: ADX calculation will now use historical data')
else:
    print('ERROR: Could not find the code section to fix')
