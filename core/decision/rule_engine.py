"""
AUTOBOT Decision Engine - Rule Engine
Immutable rule-based decision making system
"""
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod

from core.state import TradeSignal, MarketRegime

logger = logging.getLogger("autobot.decision.rule_engine")


class RuleType:
    """Rule classification for veto logic"""
    TREND = "TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"
    COMBO = "COMBO"


@dataclass
class Rule:
    """A single trading rule"""
    name: str
    condition: Callable
    bias_score: float
    allowed_regimes: List[MarketRegime]
    min_confidence: float = 0.5
    rule_type: str = RuleType.MEAN_REVERSION


class RuleEngine:
    """Evaluates trading rules and generates signals"""
    
    def __init__(self):
        self._rules: Dict[str, Rule] = {}
        self._strategy_weights: Dict[str, float] = {}
        self._sideways_veto_enabled = True
        self._vetoed_rules_in_sideways = [RuleType.TREND, RuleType.BREAKOUT, RuleType.COMBO]
        self._allowed_in_sideways = [RuleType.MEAN_REVERSION]
    
    def register_rule(self, rule: Rule):
        self._rules[rule.name] = rule
        logger.debug(f"Rule registered: {rule.name} (type: {rule.rule_type})")
    
    def register_strategy(self, strategy_name: str, initial_weight: float = 1.0):
        self._strategy_weights[strategy_name] = initial_weight
        logger.debug(f"Strategy registered: {strategy_name}, weight: {initial_weight}")
    
    def set_strategy_weight(self, strategy_name: str, weight: float):
        if strategy_name in self._strategy_weights:
            self._strategy_weights[strategy_name] = weight
            logger.info(f"Strategy weight updated: {strategy_name} = {weight}")
    
    def _is_rule_vetoed(self, rule: Rule, current_regime: MarketRegime) -> bool:
        if not self._sideways_veto_enabled:
            return False
        if current_regime == MarketRegime.RANGE:
            if rule.rule_type in self._vetoed_rules_in_sideways:
                return True
        return False
    
    def evaluate(self, symbol: str, current_regime: MarketRegime,
                features: Dict, strategy_name: str = "default") -> TradeSignal:
        total_bias = 0.0
        active_rules = 0
        vetoed_rules = 0
        strategy_weight = self._strategy_weights.get(strategy_name, 1.0)
        
        for rule in self._rules.values():
            if current_regime not in rule.allowed_regimes:
                continue
            if self._is_rule_vetoed(rule, current_regime):
                vetoed_rules += 1
                continue
            try:
                if rule.condition(features):
                    weighted_bias = rule.bias_score * strategy_weight
                    total_bias += weighted_bias
                    active_rules += 1
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.name}: {e}")
        
        normalized_bias = max(-1.0, min(1.0, total_bias))
        confidence = min(1.0, active_rules / 5.0) if active_rules > 0 else 0.0
        activation_threshold = features.get("activation_threshold", 0.7)
        
        if abs(normalized_bias) < activation_threshold:
            action = "NEUTRAL"
        elif normalized_bias >= activation_threshold:
            action = "PROPOSE_LONG"
        else:
            action = "PROPOSE_SHORT"
        
        signal = TradeSignal(
            atr=features.get("atr", 0.0),
            suggested_price=features.get("close", 0.0),
            symbol=symbol,
            action=action,
            bias_score=normalized_bias,
            confidence=confidence,
            strategy_name=strategy_name,
            regime=current_regime,
            metadata={
                "active_rules": active_rules,
                "vetoed_rules": vetoed_rules,
                "total_bias": total_bias,
                "strategy_weight": strategy_weight
            }
        )
        
        logger.info(f"Signal: {symbol} {action} bias={normalized_bias:.3f} conf={confidence:.2f} (active={active_rules}, vetoed={vetoed_rules})")
        return signal
    
    def get_strategy_weights(self) -> Dict[str, float]:
        return self._strategy_weights.copy()
