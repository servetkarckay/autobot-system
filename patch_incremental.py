import re

# Read the file
with open('/root/autobot_system/core/feature_engine/incremental_indicators.py', 'r') as f:
    content = f.read()

# Add import at the top
import_line = 'from .stateful_adx import StatefulADX\n'

if import_line not in content:
    content = import_line + content

# Update __init__ to add StatefulADX
old_init = 'self.indicators: Dict[str, Dict[str, any]] = {s: {} for s in symbols}'
new_init = '''self.indicators: Dict[str, Dict[str, any]] = {s: {} for s in symbols}
        
        # Add StatefulADX for each symbol
        self._adx_calculators: Dict[str, StatefulADX] = {s: StatefulADX(period=14) for s in symbols}'''

if old_init in content:
    content = content.replace(old_init, new_init)

# Update seed_indicators to seed ADX
old_seed = 'self._is_seeded[symbol] = True'
new_seed = '''self._is_seeded[symbol] = True
            
            # Seed StatefulADX
            if symbol in self._adx_calculators:
                self._adx_calculators[symbol].seed(df)'''

if old_seed in content:
    content = content.replace(old_seed, new_seed)

# Update calculate_features to use StatefulADX
old_calc = '''        # Incremental update for EMA
        if 'EMA_20' in self.indicators[symbol]:
            features['EMA_20'] = self.indicators[symbol]['EMA_20'].update(new_price)
        if 'EMA_50' in self.indicators[symbol]:
            features['EMA_50'] = self.indicators[symbol]['EMA_50'].update(new_price)'''

new_calc = '''        # Incremental update for EMA
        if 'EMA_20' in self.indicators[symbol]:
            features['EMA_20'] = self.indicators[symbol]['EMA_20'].update(new_price)
        if 'EMA_50' in self.indicators[symbol]:
            features['EMA_50'] = self.indicators[symbol]['EMA_50'].update(new_price)
        
        # Incremental update for ADX using StatefulADX
        if symbol in self._adx_calculators:
            adx_calc = self._adx_calculators[symbol]
            if adx_calc.is_seeded():
                # Get OHLC from buffer
                if full_data is not None and len(full_data) > 0:
                    last_high = full_data['high'].iloc[-1]
                    last_low = full_data['low'].iloc[-1]
                    last_close = full_data['close'].iloc[-1]
                    
                    adx_value = adx_calc.update(last_high, last_low, last_close)
                    features['adx'] = adx_value
                    logger.debug(f"[ADX INC] {symbol}: ADX={adx_value:.1f}")
                else:
                    features['adx'] = adx_calc.get_adx()
            else:
                features['adx'] = 20.0'''

if old_calc in content:
    content = content.replace(old_calc, new_calc)

# Write back
with open('/root/autobot_system/core/feature_engine/incremental_indicators.py', 'w') as f:
    f.write(content)

print('PATCH APPLIED: StatefulADX integrated')
