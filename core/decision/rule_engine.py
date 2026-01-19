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


@dataclass
class Rule:
    """A single trading rule"""
    name: str
    condition: Callable  # Function that returns True if rule triggers
    bias_score: float  # Contribution to total bias (-1 to +1)
    allowed_regimes: List[MarketRegime]
    min_confidence: float = 0.5


class RuleEngine:
    """Evaluates trading rules and generates signals"""
    
    def __init__(self):
        self._rules: Dict[str, Rule] = {}
        self._strategy_weights: Dict[str, float] = {}
    
    def register_rule(self, rule: Rule):
        """Register a new trading rule"""
        self._rules[rule.name] = rule
        logger.debug(f"Rule registered: {rule.name}")
    
    def register_strategy(self, strategy_name: str, initial_weight: float = 1.0):
        """Register a strategy for weight tracking"""
        self._strategy_weights[strategy_name] = initial_weight
        logger.debug(f"Strategy registered: {strategy_name}, weight: {initial_weight}")
    
    def set_strategy_weight(self, strategy_name: str, weight: float):
        """Update strategy weight (called by Adaptive Engine)"""
        if strategy_name in self._strategy_weights:
            self._strategy_weights[strategy_name] = weight
            logger.info(f"Strategy weight updated: {strategy_name} = {weight}")
    
    def evaluate(self, symbol: str, current_regime: MarketRegime,
                features: Dict, strategy_name: str = "default") -> TradeSignal:
        """
        Evaluate all applicable rules and generate a trading signal.
        
        Args:
            symbol: Trading pair symbol
            current_regime: Current detected market regime
            features: Dictionary of feature values
            strategy_name: Name of the strategy
        
        Returns:
            TradeSignal with action, bias_score, and confidence
        """
        
        total_bias = 0.0
        active_rules = 0
        strategy_weight = self._strategy_weights.get(strategy_name, 1.0)
        
        for rule in self._rules.values():
            # Skip rules not applicable to current regime
            if current_regime not in rule.allowed_regimes:
                continue
            
            # Check if rule condition is met
            try:
                if rule.condition(features):
                    weighted_bias = rule.bias_score * strategy_weight
                    total_bias += weighted_bias
                    active_rules += 1
                    logger.debug(f"Rule triggered: {rule.name}, bias: {weighted_bias:.3f}")
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.name}: {e}")
        
        # Normalize bias to -1.0 to +1.0 range
        normalized_bias = max(-1.0, min(1.0, total_bias))
        
        # Calculate confidence based on number of active rules
        confidence = min(1.0, active_rules / 5.0) if active_rules > 0 else 0.0
        
        # Determine action based on bias and activation threshold
        # Note: activation_threshold is from settings, accessed via features dict or config
        activation_threshold = features.get("activation_threshold", 0.7)
        
        if abs(normalized_bias) < activation_threshold:
            action = "NEUTRAL"
        elif normalized_bias >= activation_threshold:
            action = "PROPOSE_LONG"
        else:
            action = "PROPOSE_SHORT"
        
        signal = TradeSignal(
            symbol=symbol,
            action=action,
            bias_score=normalized_bias,
            confidence=confidence,
            strategy_name=strategy_name,
            regime=current_regime,
            metadata={
                "active_rules": active_rules,
                "total_bias": total_bias,
                "strategy_weight": strategy_weight
            }
        )
        
        logger.info(f"Signal generated: {symbol} {action} bias={normalized_bias:.3f} confidence={confidence:.2f}")
        return signal
    
    def get_strategy_weights(self) -> Dict[str, float]:
        """Get current strategy weights"""
        return self._strategy_weights.copy()
