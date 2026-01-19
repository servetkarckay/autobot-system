"""
AUTOBOT Decision Engine - Bias Generator
Aggregates signals and produces final bias scores
"""
import logging
from typing import List, Dict, Optional

from core.state import TradeSignal, MarketRegime

logger = logging.getLogger("autobot.decision.bias")


class BiasAggregator:
    """Aggregates multiple signals into a final bias score"""
    
    def __init__(self, activation_threshold: float = 0.7):
        self.activation_threshold = activation_threshold
        self._signal_history: List[TradeSignal] = []
    
    def aggregate(self, signals: List[TradeSignal], 
                 strategy_weights: Dict[str, float]) -> TradeSignal:
        """
        Aggregate multiple signals into a single trading decision.
        
        Args:
            signals: List of signals from different strategies
            strategy_weights: Weight for each strategy
        
        Returns:
            Aggregated TradeSignal
        """
        
        if not signals:
            logger.warning("No signals to aggregate")
            return TradeSignal(
                symbol="",
                action="NEUTRAL",
                bias_score=0.0,
                confidence=0.0,
                strategy_name="aggregated",
                regime=MarketRegime.UNKNOWN
            )
        
        # Verify all signals are for the same symbol
        symbols = set(s.symbol for s in signals)
        if len(symbols) != 1:
            logger.error(f"Signals for multiple symbols: {symbols}")
            return signals[0]  # Return first signal
        
        symbol = signals[0].symbol
        regime = signals[0].regime
        
        # Calculate weighted bias
        total_weight = 0.0
        weighted_bias = 0.0
        
        for signal in signals:
            weight = strategy_weights.get(signal.strategy_name, 1.0)
            if signal.action != "NEUTRAL":
                weighted_bias += signal.bias_score * weight * signal.confidence
                total_weight += weight * signal.confidence
        
        # Normalize
        if total_weight > 0:
            final_bias = weighted_bias / total_weight
        else:
            final_bias = 0.0
        
        # Clamp to valid range
        final_bias = max(-1.0, min(1.0, final_bias))
        
        # Determine action
        if abs(final_bias) < self.activation_threshold:
            action = "NEUTRAL"
        elif final_bias >= self.activation_threshold:
            action = "PROPOSE_LONG"
        else:
            action = "PROPOSE_SHORT"
        
        # Calculate confidence based on consensus
        long_votes = sum(1 for s in signals if s.action == "PROPOSE_LONG")
        short_votes = sum(1 for s in signals if s.action == "PROPOSE_SHORT")
        total_votes = long_votes + short_votes
        
        if total_votes > 0:
            consensus_ratio = max(long_votes, short_votes) / total_votes
            confidence = consensus_ratio
        else:
            confidence = 0.0
        
        aggregated_signal = TradeSignal(
            symbol=symbol,
            action=action,
            bias_score=final_bias,
            confidence=confidence,
            strategy_name="aggregated",
            regime=regime,
            metadata={
                "input_signals": len(signals),
                "long_votes": long_votes,
                "short_votes": short_votes,
                "total_weight": total_weight
            }
        )
        
        logger.info(f"Aggregated signal: {symbol} {action} bias={final_bias:.3f}")
        
        # Store in history
        self._signal_history.append(aggregated_signal)
        if len(self._signal_history) > 1000:
            self._signal_history = self._signal_history[-1000:]
        
        return aggregated_signal
