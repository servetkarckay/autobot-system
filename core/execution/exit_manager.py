"""
AUTOBOT Exit Manager - Production Ready
Donchian + ADX Momentum Exit Strategy

KRİTİK DÜZELTMELER UYGULANDI:
1. ADX düşüş kontrolü (adx_prev > adx)
2. Sembol bazlı regime takibi
3. Bar başına tek exit kontrolü

DEBUG LOGS: Detaylı orkestrasyon logları eklendi
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict
from datetime import datetime, timezone

from core.state import Position, MarketRegime

logger = logging.getLogger("autobot.execution.exit")


@dataclass
class ExitSignal:
    """Exit sinyali"""
    should_exit: bool
    reason: str
    exit_type: str  # REGIME_CHANGE, MOMENTUM_LOSS, DONCHIAN_BREAK, STOP_LOSS
    urgency: str    # IMMEDIATE, NEXT_BAR


@dataclass
class ExitMetadata:
    """Exit metadata for position"""
    adx_at_entry: float = 0.0
    adx_prev: float = 0.0
    regime_at_entry: MarketRegime = MarketRegime.UNKNOWN
    last_exit_check_ts: Optional[int] = None  # Bar timestamp (ms)


class ExitManager:
    """
    Donchian + ADX Momentum Exit - Production Version

    Exit kuralları:
    1. Donchian 20-bar break (klasik Turtle)
    2. ADX momentum kaybı (ADX DÜŞÜYOR ve kârlı)
    3. Sembol bazlı regime değişimi
    4. Stop loss (mevcut sistem korunacak)
    """

    def __init__(
        self,
        donchian_period: int = 20,
        adx_threshold: float = 20.0,
        min_r_profit: float = 1.0  # Minimum 1R kârı (opsiyonel)
    ):
        self.donchian_period = donchian_period
        self.adx_threshold = adx_threshold
        self.min_r_profit = min_r_profit

        # Sembol bazlı regime takibi
        self._symbol_regimes: Dict[str, MarketRegime] = {}

        # ADX geçmişi (düşüş kontrolü için)
        self._symbol_adx_history: Dict[str, list] = {}

        logger.info(
            f"[EXIT MANAGER] Initialized: Donchian={donchian_period}, "
            f"ADX={adx_threshold}, MinR={min_r_profit}"
        )
        logger.debug("[EXIT MANAGER] Exit rules loaded: STOP_LOSS > REGIME_CHANGE > MOMENTUM_LOSS > DONCHIAN_BREAK")

    def update_symbol_regime(self, symbol: str, regime: MarketRegime):
        """Sembol için regime güncelle"""
        old_regime = self._symbol_regimes.get(symbol, MarketRegime.UNKNOWN)
        self._symbol_regimes[symbol] = regime

        if old_regime != regime:
            logger.debug(f"[EXIT REGIME] {symbol}: {old_regime.value} → {regime.value}")

    def update_symbol_adx(self, symbol: str, adx: float, timestamp: int):
        """
        Sembol için ADX güncelle (düşüş kontrolü için)

        Son 3 değeri tutar - düşüş trendini tespit için yeterli
        """
        if symbol not in self._symbol_adx_history:
            self._symbol_adx_history[symbol] = []

        history = self._symbol_adx_history[symbol]
        old_adx = history[-1][1] if history else None

        history.append((timestamp, adx))

        # Eski değerleri temizle (1 saatten eski)
        now = datetime.now(timezone.utc).timestamp() * 1000
        cutoff = now - 3600000  # 1 saat
        self._symbol_adx_history[symbol] = [
            (ts, val) for ts, val in history if ts > cutoff
        ]

        # Max 3 değer tut
        if len(self._symbol_adx_history[symbol]) > 3:
            self._symbol_adx_history[symbol] = self._symbol_adx_history[symbol][-3:]

        # Debug: ADX değişimi
        if old_adx is not None:
            change = adx - old_adx
            logger.debug(f"[EXIT ADX] {symbol}: {old_adx:.1f} → {adx:.1f} ({change:+.1f})")

    def _get_adx_trend(self, symbol: str, current_adx: float) -> str:
        """
        ADX trendini belirle

        Returns:
            'FALLING' - ADX düşüyor
            'RISING' - ADX yükseliyor
            'STABLE' - ADX stabil
            'UNKNOWN' - Yetersiz veri
        """
        history = self._symbol_adx_history.get(symbol, [])

        if len(history) < 2:
            logger.debug(f"[EXIT ADX TREND] {symbol}: UNKNOWN (insufficient data: {len(history)})")
            return 'UNKNOWN'

        # Son 3 değeri al
        recent = history[-3:] if len(history) >= 3 else history

        # Debug: ADX geçmişi
        adx_values = [f"{v[1]:.1f}" for v in recent]
        logger.debug(f"[EXIT ADX HISTORY] {symbol}: [{', '.join(adx_values)}]")

        # Trend yönünü kontrol et
        all_falling = all(recent[i][1] > recent[i+1][1] for i in range(len(recent)-1))
        all_rising = all(recent[i][1] < recent[i+1][1] for i in range(len(recent)-1))

        if all_falling:
            logger.debug(f"[EXIT ADX TREND] {symbol}: FALLING (ADX decreasing)")
            return 'FALLING'
        elif all_rising:
            logger.debug(f"[EXIT ADX TREND] {symbol}: RISING (ADX increasing)")
            return 'RISING'
        else:
            logger.debug(f"[EXIT ADX TREND] {symbol}: STABLE (ADX mixed)")
            return 'STABLE'

    def check_exit(
        self,
        position: Position,
        features: dict,
        symbol: str
    ) -> ExitSignal:
        """
        Pozisyon için exit kontrolü

        Args:
            position: Açık pozisyon
            features: Teknik indikatörler
            symbol: Trading sembolü

        Returns:
            ExitSignal
        """

        close = features.get("close", 0)
        high_20 = features.get("high_20", 0)
        low_20 = features.get("low_20", 0)
        adx = features.get("adx", 0)
        bar_timestamp = features.get("timestamp", 0)  # milliseconds

        # Debug: Pozisyon bilgisi
        logger.debug(
            f"[EXIT CHECK] {symbol} {position.side} | "
            f"Entry: {position.entry_price:.2f} | Current: {close:.2f} | "
            f"PnL: {position.unrealized_pnl:.2f} | "
            f"ADX: {adx:.1f} | high_20: {high_20:.2f} | low_20: {low_20:.2f}"
        )

        # Exit metadata yoksa oluştur
        if not hasattr(position, 'exit_metadata'):
            position.exit_metadata = ExitMetadata()
            position.exit_metadata.regime_at_entry = position.regime_at_entry
            position.exit_metadata.adx_at_entry = adx
            logger.debug(f"[EXIT METADATA] Created for {symbol}")

        metadata = position.exit_metadata

        # ========== KRITIK: İlk bar'da exit atla ==========
        # Binance -2022 hatasını önlemek için: Pozisyon açıldıktan sonraki
        # ilk 60 saniye içinde exit kontrolünü atla (emir henüz match olmamış olabilir)
        now = datetime.now(timezone.utc)
        position_age_seconds = (now - position.entry_time).total_seconds()

        MIN_POSITION_AGE_SECONDS = 60  # İlk 60 saniyede exit yok

        if position_age_seconds < MIN_POSITION_AGE_SECONDS:
            logger.debug(
                f"[EXIT SKIP] {symbol}: Position too young ({position_age_seconds:.1f}s < {MIN_POSITION_AGE_SECONDS}s), "
                f"skipping exit check to avoid Binance -2022 error"
            )
            return ExitSignal(
                should_exit=False,
                reason="",
                exit_type="",
                urgency=""
            )

        # ========== KRİTİK: Bar başına tek exit kontrolü ==========
        if metadata.last_exit_check_ts and bar_timestamp <= metadata.last_exit_check_ts:
            # Bu bar zaten kontrol edildi
            logger.debug(f"[EXIT THROTTLE] {symbol}: Bar already checked (ts={bar_timestamp})")
            return ExitSignal(
                should_exit=False,
                reason="",
                exit_type="",
                urgency=""
            )

        # Update last check timestamp
        metadata.last_exit_check_ts = bar_timestamp

        # ADX history güncelle
        self.update_symbol_adx(symbol, adx, bar_timestamp)
        adx_trend = self._get_adx_trend(symbol, adx)

        # Sembol bazlı regime al
        symbol_regime = self._symbol_regimes.get(symbol, MarketRegime.UNKNOWN)

        logger.debug(
            f"[EXIT CONTEXT] {symbol} | Regime: {symbol_regime.value} | "
            f"ADX Trend: {adx_trend} | Bar TS: {bar_timestamp}"
        )

        # ========== Stop loss kontrolü (en öncelikli) ==========
        stop_exit = self._check_stop_loss(position, close)
        if stop_exit.should_exit:
            logger.warning(f"[EXIT TRIGGERED] {symbol} | Type: STOP_LOSS | {stop_exit.reason}")
            return stop_exit

        # ========== Regime değişimi kontrolü ==========
        regime_exit = self._check_regime_change(position, symbol_regime, symbol)
        if regime_exit.should_exit:
            logger.warning(f"[EXIT TRIGGERED] {symbol} | Type: REGIME_CHANGE | {regime_exit.reason}")
            return regime_exit

        # ========== Momentum kaybı kontrolü ==========
        logger.debug(f"[EXIT CHECKING] {symbol} | Momentum Loss | ADX trend: {adx_trend}, threshold: {self.adx_threshold}")
        momentum_exit = self._check_momentum_loss(
            position, features, close, adx, adx_trend
        )
        if momentum_exit.should_exit:
            logger.warning(f"[EXIT TRIGGERED] {symbol} | Type: MOMENTUM_LOSS | {momentum_exit.reason}")
            return momentum_exit

        # ========== Donchian break kontrolü ==========
        logger.debug(f"[EXIT CHECKING] {symbol} | Donchian Break | close: {close:.2f}, high_20: {high_20:.2f}, low_20: {low_20:.2f}")
        donchian_exit = self._check_donchian_break(position, features, close)
        if donchian_exit.should_exit:
            logger.warning(f"[EXIT TRIGGERED] {symbol} | Type: DONCHIAN_BREAK | {donchian_exit.reason}")
            return donchian_exit

        # Exit yok
        logger.debug(f"[EXIT NO SIGNAL] {symbol} | No exit condition met")
        return ExitSignal(
            should_exit=False,
            reason="",
            exit_type="",
            urgency=""
        )

    def _check_stop_loss(self, position: Position, close: float) -> ExitSignal:
        """Stop loss kontrolü (mevcut sistem korunacak)"""

        if position.stop_loss_price:
            if position.side == "LONG" and close <= position.stop_loss_price:
                logger.debug(
                    f"[EXIT STOP LOSS] {position.symbol} LONG | "
                    f"close: {close:.2f} <= stop: {position.stop_loss_price:.2f}"
                )
                return ExitSignal(
                    should_exit=True,
                    reason=f"Stop loss hit: {close:.2f} <= {position.stop_loss_price:.2f}",
                    exit_type="STOP_LOSS",
                    urgency="IMMEDIATE"
                )
            elif position.side == "SHORT" and close >= position.stop_loss_price:
                logger.debug(
                    f"[EXIT STOP LOSS] {position.symbol} SHORT | "
                    f"close: {close:.2f} >= stop: {position.stop_loss_price:.2f}"
                )
                return ExitSignal(
                    should_exit=True,
                    reason=f"Stop loss hit: {close:.2f} >= {position.stop_loss_price:.2f}",
                    exit_type="STOP_LOSS",
                    urgency="IMMEDIATE"
                )

        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _check_regime_change(
        self,
        position: Position,
        current_regime: MarketRegime,
        symbol: str
    ) -> ExitSignal:
        """
        Regime değişimi kontrolü (SEMBOL BAZLI)

        LONG: Regime BULL_TREND değilse exit
        SHORT: Regime BEAR_TREND değilse exit
        """

        expected_regime = MarketRegime.BULL_TREND if position.side == "LONG" else MarketRegime.BEAR_TREND

        logger.debug(
            f"[EXIT REGIME CHECK] {symbol} {position.side} | "
            f"Expected: {expected_regime.value}, Current: {current_regime.value}"
        )

        if position.side == "LONG":
            if current_regime != MarketRegime.BULL_TREND:
                return ExitSignal(
                    should_exit=True,
                    reason=f"Regime changed for {symbol}: BULL → {current_regime.value}",
                    exit_type="REGIME_CHANGE",
                    urgency="IMMEDIATE"
                )

        elif position.side == "SHORT":
            if current_regime != MarketRegime.BEAR_TREND:
                return ExitSignal(
                    should_exit=True,
                    reason=f"Regime changed for {symbol}: BEAR → {current_regime.value}",
                    exit_type="REGIME_CHANGE",
                    urgency="IMMEDIATE"
                )

        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _check_momentum_loss(
        self,
        position: Position,
        features: dict,
        close: float,
        adx: float,
        adx_trend: str
    ) -> ExitSignal:
        """
        Momentum kaybı kontrolü

        KRİTİK DÜZELTME:
        - ADX < 20 değil
        - ADX DÜŞÜYOR (adx_trend == 'FALLING')
        - VE kârlıyız
        - VE fiyat Donchian içinde (trend break)

        Optional: R-based kontrol (1R min)
        """

        # ADX düşüş kontrolü (KRİTİK)
        if adx_trend != 'FALLING':
            logger.debug(
                f"[EXIT MOMENTUM] {position.symbol}: ADX not falling (trend={adx_trend})"
            )
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        # ADX threshold altına indi mi?
        if adx >= self.adx_threshold:
            logger.debug(
                f"[EXIT MOMENTUM] {position.symbol}: ADX above threshold "
                f"({adx:.1f} >= {self.adx_threshold})"
            )
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        # Kâr kontrolü
        atr = features.get("atr", 0)
        r_profit = self._calculate_r_profit(position, close, atr)

        logger.debug(
            f"[EXIT MOMENTUM] {position.symbol}: R-profit = {r_profit:.2f} (min: {self.min_r_profit})"
        )

        if r_profit < self.min_r_profit:
            # Minimum R kârı yok, bekle
            logger.debug(
                f"[EXIT MOMENTUM] {position.symbol}: R-profit below minimum, waiting"
            )
            return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

        # Donchian içi kontrolü
        high_20 = features.get("high_20", 0)
        low_20 = features.get("low_20", 0)

        if position.side == "LONG":
            # LONG: Kârdayız, ADX düşüyor, fiyat high_20'ye çıkmadı
            in_donchian = close < high_20
            logger.debug(
                f"[EXIT MOMENTUM] {position.symbol} LONG: "
                f"close({close:.2f}) < high_20({high_20:.2f}) = {in_donchian}"
            )

            if in_donchian:
                return ExitSignal(
                    should_exit=True,
                    reason=(
                        f"Momentum loss for {position.symbol}: "
                        f"ADX={adx:.1f} (<{self.adx_threshold}, FALLING), "
                        f"R=+{r_profit:.2f}, "
                        f"close({close:.2f}) < high_20({high_20:.2f})"
                    ),
                    exit_type="MOMENTUM_LOSS",
                    urgency="NEXT_BAR"
                )

        elif position.side == "SHORT":
            # SHORT: Kârdayız, ADX düşüyor, fiyat low_20'ye düşmedi
            in_donchian = close > low_20
            logger.debug(
                f"[EXIT MOMENTUM] {position.symbol} SHORT: "
                f"close({close:.2f}) > low_20({low_20:.2f}) = {in_donchian}"
            )

            if in_donchian:
                return ExitSignal(
                    should_exit=True,
                    reason=(
                        f"Momentum loss for {position.symbol}: "
                        f"ADX={adx:.1f} (<{self.adx_threshold}, FALLING), "
                        f"R=+{r_profit:.2f}, "
                        f"close({close:.2f}) > low_20({low_20:.2f})"
                    ),
                    exit_type="MOMENTUM_LOSS",
                    urgency="NEXT_BAR"
                )

        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _check_donchian_break(
        self,
        position: Position,
        features: dict,
        close: float
    ) -> ExitSignal:
        """
        Donchian break kontrolü (Klasik Turtle exit)

        LONG: close < low_20
        SHORT: close > high_20
        """

        high_20 = features.get("high_20", 0)
        low_20 = features.get("low_20", 0)

        if position.side == "LONG":
            broken = close < low_20
            logger.debug(
                f"[EXIT DONCHIAN] {position.symbol} LONG: "
                f"close({close:.2f}) < low_20({low_20:.2f}) = {broken}"
            )

            if broken:
                return ExitSignal(
                    should_exit=True,
                    reason=(
                        f"Donchian break for {position.symbol}: "
                        f"{close:.2f} < {low_20:.2f} (20-bar low)"
                    ),
                    exit_type="DONCHIAN_BREAK",
                    urgency="NEXT_BAR"
                )

        elif position.side == "SHORT":
            broken = close > high_20
            logger.debug(
                f"[EXIT DONCHIAN] {position.symbol} SHORT: "
                f"close({close:.2f}) > high_20({high_20:.2f}) = {broken}"
            )

            if broken:
                return ExitSignal(
                    should_exit=True,
                    reason=(
                        f"Donchian break for {position.symbol}: "
                        f"{close:.2f} > {high_20:.2f} (20-bar high)"
                    ),
                    exit_type="DONCHIAN_BREAK",
                    urgency="NEXT_BAR"
                )

        return ExitSignal(should_exit=False, reason="", exit_type="", urgency="")

    def _calculate_r_profit(self, position: Position, close: float, atr: float) -> float:
        """
        R-multiple kâr hesabı

        R = (current_price - entry_price) / ATR
        """
        if atr <= 0:
            # ATR yok, yüzde kullan (fallback)
            if position.side == "LONG":
                return (close - position.entry_price) / position.entry_price * 100
            else:
                return (position.entry_price - close) / position.entry_price * 100

        if position.side == "LONG":
            r_profit = (close - position.entry_price) / atr
        else:
            r_profit = (position.entry_price - close) / atr

        return r_profit


# Global instance
exit_manager = ExitManager()
