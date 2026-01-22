from core.state_manager import MarketRegime
from core.decision.rule_engine import Rule, RuleType
from core.constants import Indicator
import logging

logger = logging.getLogger('autobot.strategies')


def _register_breakout_rules(rule_engine):
    """Registers breakout-based trading rules."""
    # Note: 'breakout' features are calculated directly in event_engine for now,
    # so they don't have a dedicated Indicator Enum.
    rule_engine.register_rule(Rule(
        name='TURTLE_20DAY_BREAKOUT_LONG',
        condition=lambda f: f.get('breakout_20_long', False),
        bias_score=0.7,
        allowed_regimes=[MarketRegime.BULL_TREND, MarketRegime.RANGE],
        min_confidence=0.6,
        rule_type=RuleType.BREAKOUT
    ))
    
    rule_engine.register_rule(Rule(
        name='TURTLE_20DAY_BREAKOUT_SHORT',
        condition=lambda f: f.get('breakout_20_short', False),
        bias_score=-0.7,
        allowed_regimes=[MarketRegime.BEAR_TREND, MarketRegime.RANGE],
        min_confidence=0.6,
        rule_type=RuleType.BREAKOUT
    ))

def _register_mean_reversion_rules(rule_engine):
    """Registers mean-reversion trading rules with strict regime filtering."""
    rule_engine.register_rule(Rule(
        name='RSI_OVERSOLD_LONG',
        condition=lambda f: f.get(Indicator.RSI.value, 50) < 30,
        required_features=[Indicator.RSI],
        bias_score=0.6,
        allowed_regimes=[MarketRegime.RANGE],
        min_confidence=0.5,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='RSI_OVERBOUGHT_SHORT',
        condition=lambda f: f.get(Indicator.RSI.value, 50) > 70,
        required_features=[Indicator.RSI],
        bias_score=-0.6,
        allowed_regimes=[MarketRegime.RANGE],
        min_confidence=0.5,
        rule_type=RuleType.MEAN_REVERSION
    ))

def _register_trend_rules(rule_engine):
    """Registers trend-following trading rules."""
    # Note: 'ema_20_above_ema_50' and 'adx' are placeholders for now.
    # A full implementation would add them to the Indicator Enum.
    rule_engine.register_rule(Rule(
        name='STRONG_UPTREND',
        condition=lambda f: f.get('adx', 0) > 25 and f.get('ema_20_above_ema_50', False) and f.get(Indicator.RSI.value, 50) > 50,
        required_features=[Indicator.RSI, Indicator.EMA_20, Indicator.EMA_50],
        bias_score=0.7,
        allowed_regimes=[MarketRegime.BULL_TREND],
        min_confidence=0.6,
        rule_type=RuleType.TREND
    ))
    
    rule_engine.register_rule(Rule(
        name='STRONG_DOWNTREND',
        condition=lambda f: f.get('adx', 0) > 25 and not f.get('ema_20_above_ema_50', True) and f.get(Indicator.RSI.value, 50) < 50,
        required_features=[Indicator.RSI, Indicator.EMA_20, Indicator.EMA_50],
        bias_score=-0.7,
        allowed_regimes=[MarketRegime.BEAR_TREND],
        min_confidence=0.6,
        rule_type=RuleType.TREND
    ))

def _register_combo_rules(rule_engine):
    """Registers rules that combine multiple strong signals."""
    rule_engine.register_rule(Rule(
        name='SUPER_BULLISH',
        condition=lambda f: f.get(Indicator.RSI.value, 50) < 35 and f.get('ema_20_above_ema_50', False) and f.get('close', 0) < f.get('bb_middle', 0) and f.get('adx', 0) > 20,
        required_features=[Indicator.RSI, Indicator.EMA_20, Indicator.EMA_50],
        bias_score=0.9,
        allowed_regimes=[MarketRegime.BULL_TREND, MarketRegime.RANGE],
        min_confidence=0.7,
        rule_type=RuleType.COMBO
    ))
    
    rule_engine.register_rule(Rule(
        name='SUPER_BEARISH',
        condition=lambda f: f.get(Indicator.RSI.value, 50) > 65 and not f.get('ema_20_above_ema_50', True) and f.get('close', 0) > f.get('bb_middle', 0) and f.get('adx', 0) > 20,
        required_features=[Indicator.RSI, Indicator.EMA_20, Indicator.EMA_50],
        bias_score=-0.9,
        allowed_regimes=[MarketRegime.BEAR_TREND, MarketRegime.RANGE],
        min_confidence=0.7,
        rule_type=RuleType.COMBO
    ))

def register_all_rules(rule_engine, indicator_calculator=None):
    """
    Registers all trading rules with the rule engine by calling modular helpers.
    """
    _register_breakout_rules(rule_engine)
    _register_mean_reversion_rules(rule_engine)
    _register_trend_rules(rule_engine)
    _register_combo_rules(rule_engine)
    
    logger.info(f'Trading rules registered: {len(rule_engine._rules)} rules loaded')
