"""
AUTOBOT Decision Engine - Rule Engine
Immutable rule-based decision making system
"""
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from core.state_manager import TradeSignal, MarketRegime
from core.constants import Indicator

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
    required_features: List[Indicator] = field(default_factory=list)
    min_confidence: float = 0.5
    rule_type: str = RuleType.MEAN_REVERSION


class RuleEngine:
    """Evaluates trading rules and generates signals"""
    
    def __init__(self):
        self._rules: Dict[str, Rule] = {}
        self.required_features: set[Indicator] = set()
        self._strategy_weights: Dict[str, float] = {}
        self._sideways_veto_enabled = True
        self._vetoed_rules_in_sideways = [RuleType.TREND, RuleType.BREAKOUT, RuleType.COMBO]
        self._allowed_in_sideways = [RuleType.MEAN_REVERSION]
        self.regime: MarketRegime = MarketRegime.UNKNOWN
    
    def register_rule(self, rule: Rule):
        self._rules[rule.name] = rule
        for feature in rule.required_features:
            self.required_features.add(feature)
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
        elif current_regime == MarketRegime.BEAR_TREND:
            # In bear trend, veto LONG breakouts
            if rule.rule_type == "BREAKOUT" and "LONG" in rule.name.upper():
                return True
        return False
    
    def _get_veto_reason(self, rule: Rule, current_regime: MarketRegime) -> str:
        """Get detailed veto reason based on rule type and regime"""
        if current_regime == MarketRegime.RANGE:
            if rule.rule_type == "TREND":
                return "TREND_NOT_ALLOWED_IN_RANGE"
            elif rule.rule_type == "BREAKOUT":
                return "BREAKOUT_NOT_CONFIRMED_IN_RANGE"
            elif rule.rule_type == "COMBO":
                return "COMBO_NOT_ALLOWED_IN_RANGE"
        elif current_regime == MarketRegime.BEAR_TREND:
            if rule.rule_type == "BREAKOUT" and "LONG" in rule.name.upper():
                return "LONG_BREAKOUT_IN_BEAR_TREND"
            elif rule.rule_type == "BREAKOUT" and "SHORT" in rule.name.upper():
                return "SHORT_BREAKOUT_IN_BEAR_TREND"
        return f"{rule.rule_type}_VETOED"

    
    def evaluate(self, symbol: str, current_regime: MarketRegime,
                features: Dict, strategy_name: str = "default") -> TradeSignal:
        # Update rule engine's regime
        self.regime = current_regime
        
        # Log regime source
        global_regime = MarketRegime.UNKNOWN  # Will be updated from global state if available
        try:
            from core.state_manager import StateManager
            state_mgr = StateManager()
            state = state_mgr.load_state()
            if state and symbol in state.symbol_regimes:
                global_regime = state.symbol_regimes[symbol]
        except Exception:
            pass
        
        logger.debug(
            f"[REGIME_SOURCE] "
            f"rule_engine_regime={self.regime.value} "
            f"global_regime={global_regime.value}"
        )
        
        total_bias = 0.0
        active_rules = 0
        vetoed_rules = 0
        strategy_weight = self._strategy_weights.get(strategy_name, 1.0)
        
        for rule in self._rules.values():
            if current_regime not in rule.allowed_regimes:
                continue
            if self._is_rule_vetoed(rule, current_regime):
                vetoed_rules += 1
                veto_reason = self._get_veto_reason(rule, current_regime)
                logger.debug(f"[VETO] {rule.name}: {veto_reason} | regime_seen={current_regime.value}")
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
