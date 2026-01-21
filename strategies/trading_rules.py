from core.state import MarketRegime
from core.decision.rule_engine import Rule, RuleType
import logging

logger = logging.getLogger('autobot.strategies')


def register_all_rules(rule_engine, indicator_calculator=None):
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
    
    rule_engine.register_rule(Rule(
        name='TURTLE_55DAY_BREAKOUT_LONG',
        condition=lambda f: f.get('breakout_55_long', False),
        bias_score=0.9,
        allowed_regimes=[MarketRegime.BULL_TREND],
        min_confidence=0.7,
        rule_type=RuleType.BREAKOUT
    ))
    
    rule_engine.register_rule(Rule(
        name='TURTLE_55DAY_BREAKOUT_SHORT',
        condition=lambda f: f.get('breakout_55_short', False),
        bias_score=-0.9,
        allowed_regimes=[MarketRegime.BEAR_TREND],
        min_confidence=0.7,
        rule_type=RuleType.BREAKOUT
    ))
    
    rule_engine.register_rule(Rule(
        name='RSI_OVERSOLD_LONG',
        condition=lambda f: f.get('rsi', 50) < 30,
        bias_score=0.6,
        allowed_regimes=[MarketRegime.BULL_TREND, MarketRegime.RANGE],
        min_confidence=0.5,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='RSI_OVERBOUGHT_SHORT',
        condition=lambda f: f.get('rsi', 50) > 70,
        bias_score=-0.6,
        allowed_regimes=[MarketRegime.BEAR_TREND, MarketRegime.RANGE],
        min_confidence=0.5,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='RSI_EXTREME_OVERSOLD',
        condition=lambda f: f.get('rsi', 50) < 20,
        bias_score=0.8,
        allowed_regimes=[MarketRegime.BULL_TREND, MarketRegime.RANGE],
        min_confidence=0.6,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='RSI_EXTREME_OVERBOUGHT',
        condition=lambda f: f.get('rsi', 50) > 80,
        bias_score=-0.8,
        allowed_regimes=[MarketRegime.BEAR_TREND, MarketRegime.RANGE],
        min_confidence=0.6,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='GOLDEN_CROSS',
        condition=lambda f: f.get('ema_20_above_ema_50', False) and f.get('adx', 0) > 25,
        bias_score=0.5,
        allowed_regimes=[MarketRegime.BULL_TREND],
        min_confidence=0.4,
        rule_type=RuleType.TREND
    ))
    
    rule_engine.register_rule(Rule(
        name='DEATH_CROSS',
        condition=lambda f: not f.get('ema_20_above_ema_50', True) and f.get('adx', 0) > 25,
        bias_score=-0.5,
        allowed_regimes=[MarketRegime.BEAR_TREND],
        min_confidence=0.4,
        rule_type=RuleType.TREND
    ))
    
    rule_engine.register_rule(Rule(
        name='BB_OVERSOLD',
        condition=lambda f: f.get('close', 0) < f.get('bb_lower', 0) and f.get('rsi', 50) < 40,
        bias_score=0.6,
        allowed_regimes=[MarketRegime.BULL_TREND, MarketRegime.RANGE],
        min_confidence=0.5,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='BB_OVERBOUGHT',
        condition=lambda f: f.get('close', 0) > f.get('bb_upper', 0) and f.get('rsi', 50) > 60,
        bias_score=-0.6,
        allowed_regimes=[MarketRegime.BEAR_TREND, MarketRegime.RANGE],
        min_confidence=0.5,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='STOCH_OVERSOLD',
        condition=lambda f: f.get('stoch_k', 50) < 20 and f.get('stoch_d', 50) < 20,
        bias_score=0.5,
        allowed_regimes=[MarketRegime.BULL_TREND, MarketRegime.RANGE],
        min_confidence=0.4,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='STOCH_OVERBOUGHT',
        condition=lambda f: f.get('stoch_k', 50) > 80 and f.get('stoch_d', 50) > 80,
        bias_score=-0.5,
        allowed_regimes=[MarketRegime.BEAR_TREND, MarketRegime.RANGE],
        min_confidence=0.4,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='STOCH_BULLISH_CROSS',
        condition=lambda f: f.get('stoch_k', 50) > f.get('stoch_d', 50) and f.get('stoch_k', 0) < 80,
        bias_score=0.4,
        allowed_regimes=[MarketRegime.BULL_TREND, MarketRegime.RANGE],
        min_confidence=0.3,
        rule_type=RuleType.MEAN_REVERSION
    ))
    
    rule_engine.register_rule(Rule(
        name='STRONG_UPTREND',
        condition=lambda f: f.get('adx', 0) > 25 and f.get('ema_20_above_ema_50', False) and f.get('rsi', 50) > 50,
        bias_score=0.7,
        allowed_regimes=[MarketRegime.BULL_TREND],
        min_confidence=0.6,
        rule_type=RuleType.TREND
    ))
    
    rule_engine.register_rule(Rule(
        name='STRONG_DOWNTREND',
        condition=lambda f: f.get('adx', 0) > 25 and not f.get('ema_20_above_ema_50', True) and f.get('rsi', 50) < 50,
        bias_score=-0.7,
        allowed_regimes=[MarketRegime.BEAR_TREND],
        min_confidence=0.6,
        rule_type=RuleType.TREND
    ))
    
    rule_engine.register_rule(Rule(
        name='SUPER_BULLISH',
        condition=lambda f: f.get('rsi', 50) < 35 and f.get('ema_20_above_ema_50', False) and f.get('close', 0) < f.get('bb_middle', 0) and f.get('adx', 0) > 20,
        bias_score=0.9,
        allowed_regimes=[MarketRegime.BULL_TREND, MarketRegime.RANGE],
        min_confidence=0.7,
        rule_type=RuleType.COMBO
    ))
    
    rule_engine.register_rule(Rule(
        name='SUPER_BEARISH',
        condition=lambda f: f.get('rsi', 50) > 65 and not f.get('ema_20_above_ema_50', True) and f.get('close', 0) > f.get('bb_middle', 0) and f.get('adx', 0) > 20,
        bias_score=-0.9,
        allowed_regimes=[MarketRegime.BEAR_TREND, MarketRegime.RANGE],
        min_confidence=0.7,
        rule_type=RuleType.COMBO
    ))
    
    rule_engine.register_rule(Rule(
        name='MOMENTUM_BREAKOUT_LONG',
        condition=lambda f: f.get('adx', 0) > 30 and f.get('rsi', 50) > 50 and f.get('rsi', 50) < 70 and f.get('ema_20_above_ema_50', False),
        bias_score=0.6,
        allowed_regimes=[MarketRegime.BULL_TREND],
        min_confidence=0.5,
        rule_type=RuleType.TREND
    ))
    
    logger.info(f'Trading rules registered: {len(rule_engine._rules)} rules loaded')
