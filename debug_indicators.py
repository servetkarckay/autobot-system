import pandas as pd
import numpy as np
from core.feature_engine.indicators import IndicatorCalculator

# Simulate the data structure
buffer = [
    {'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5, 'volume': 1000},
    {'open': 100.5, 'high': 102.0, 'low': 100.0, 'close': 101.0, 'volume': 1100},
]

for _ in range(50):
    buffer.append({
        'open': 100.0 + np.random.random(),
        'high': 101.0 + np.random.random(),
        'low': 99.0 + np.random.random(),
        'close': 100.0 + np.random.random(),
        'volume': 1000 + np.random.randint(100)
    })

# Create DataFrame like event_engine does
df_data = {
    'open': [k['open'] for k in buffer],
    'high': [k['high'] for k in buffer],
    'low': [k['low'] for k in buffer],
    'close': [k['close'] for k in buffer],
    'volume': [k['volume'] for k in buffer]
}
df = pd.DataFrame(df_data)

print(f'DataFrame type: {type(df)}')
print(f'DataFrame shape: {df.shape}')
print(f'DataFrame head:\n{df.head()}')

# Test indicator calculator
calc = IndicatorCalculator()
features = calc.calculate_all(df)

print(f'\nCalculated {len(features)} features')
print(f'ADX: {features.get("adx", "N/A")}')
print(f'Stoch K: {features.get("stoch_k", "N/A")}')
print(f'Stoch D: {features.get("stoch_d", "N/A")}')
