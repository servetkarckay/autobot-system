import sys
sys.path.insert(0, '/root/autobot_system')

import logging
logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')

from core.decision.rule_engine import RuleEngine
from core.state_manager import MarketRegime

engine = RuleEngine()
features = {"close": 2930, "high_20": 2950, "low_20": 2900, "adx": 15}

result = engine.evaluate("ETHUSDT", MarketRegime.BEAR_TREND, features, "test")
print(f"Result: {result.action}, bias={result.bias_score}")
