"""Technical signal detector — identifies RSI, EMA cross, and volume spike signals.

This module provides pure-numeric detection functions that take a list of
candles (OHLCV dicts) and return a signal descriptor when a condition is met.

Each function returns a dict (or ``None`` when no signal is detected) with:
    {
        "type":         "rsi_overbought" | "rsi_oversold" | "ema_cross_up" | ...
        "symbol":       str,
        "value":        float (the indicator value that triggered),
        "message":      str,
        "timestamp":    ISO-8601 string of the last candle,
    }

These are consumed by the scheduler's ``check_advanced_alerts`` job which
evaluates the user's watchlist symbols and fires PriceAlert records for
any active ``rsi`` / ``ema_cross`` / ``volume_spike`` alert types.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: RSI thresholds.
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0

#: EMA periods to compare for crossover.
EMA_FAST = 20
EMA_SLOW = 50

#: Volume spike multiplier (spike when volume > multiplier * average).
VOLUME_SPIKE_MULTIPLIER = 2.0

#: Number of candles to use for the average volume calculation.
VOLUME_AVG_WINDOW = 20


# ── Indicator calculations ──────────────────────────────────────────────────


def _closes(candles: List[Dict[str, Any]]) -> List[float]:
    """Extract close prices from candle dicts, handling None/missing."""
    result: List[float] = []
    for c in candles:
        close = c.get("close")
        if close is None:
            continue
        try:
            result.append(float(close))
        except (TypeError, ValueError):
            continue
    return result


def _volumes(candles: List[Dict[str, Any]]) -> List[float]:
    """Extract volume values from candle dicts."""
    result: List[float] = []
    for c in candles:
        vol = c.get("volume")
        if vol is None:
            result.append(0.0)
            continue
        try:
            result.append(float(vol))
        except (TypeError, ValueError):
            result.append(0.0)
    return result


def calculate_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Calculate the RSI of the last close in the series.

    Uses the standard Wilder's smoothing method. Returns ``None`` if there
    aren't enough data points.
    """
    if len(closes) < period + 1:
        return None

    # Calculate price changes
    changes: List[float] = []
    for i in range(1, len(closes)):
        changes.append(closes[i] - closes[i - 1])

    # Separate gains and losses
    gains = [max(c, 0.0) for c in changes[:period]]
    losses = [max(-c, 0.0) for c in changes[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder's smoothing for the remaining changes
    for i in range(period, len(changes)):
        change = changes[i]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def calculate_ema(values: List[float], period: int) -> List[float]:
    """Calculate EMA series for the given values.

    Returns a list of the same length as ``values`` where the first
    ``period - 1`` entries are the running SMA seed (or partial average).
    """
    if not values:
        return []
    if len(values) < period:
        # Not enough data for full EMA — return simple running average.
        result: List[float] = []
        for i in range(len(values)):
            result.append(sum(values[: i + 1]) / (i + 1))
        return result

    k = 2.0 / (period + 1)
    # Seed with SMA of the first `period` values.
    ema_list: List[float] = []
    sma_seed = sum(values[:period]) / period
    for _ in range(period - 1):
        ema_list.append(sum(values[: _ + 1]) / (_ + 1))
    ema_list.append(sma_seed)

    # Walk forward.
    for i in range(period, len(values)):
        prev_ema = ema_list[-1]
        ema = values[i] * k + prev_ema * (1 - k)
        ema_list.append(ema)

    return ema_list


def _last_timestamp(candles: List[Dict[str, Any]]) -> str:
    """Return the ISO-8601 timestamp of the last candle, or current time."""
    if not candles:
        return datetime.now(timezone.utc).isoformat()
    ts = candles[-1].get("time") or candles[-1].get("timestamp")
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(ts, (int, float)):
        # Epoch ms or seconds
        if ts > 1e12:
            ts = ts / 1000
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            pass
    return str(ts)


# ── Signal detectors ──────────────────────────────────────────────────────


def detect_rsi_signals(
    symbol: str,
    candles: List[Dict[str, Any]],
    overbought: float = RSI_OVERBOUGHT,
    oversold: float = RSI_OVERSOLD,
    period: int = 14,
) -> Optional[Dict[str, Any]]:
    """Detect RSI overbought/oversold conditions.

    * RSI > ``overbought`` (default 70) → overbought signal.
    * RSI < ``oversold`` (default 30) → oversold signal.

    Returns a signal dict, or ``None`` when RSI is in the neutral zone.
    """
    closes = _closes(candles)
    if len(closes) < period + 1:
        logger.debug("RSI: not enough candles for %s (%d < %d)", symbol, len(closes), period + 1)
        return None

    rsi = calculate_rsi(closes, period)
    if rsi is None:
        return None

    timestamp = _last_timestamp(candles)

    if rsi > overbought:
        return {
            "type": "rsi_overbought",
            "symbol": symbol,
            "value": rsi,
            "message": f"⚠️ {symbol} RSI is overbought at {rsi:.1f} (>{overbought:.0f})",
            "timestamp": timestamp,
        }
    if rsi < oversold:
        return {
            "type": "rsi_oversold",
            "symbol": symbol,
            "value": rsi,
            "message": f"📈 {symbol} RSI is oversold at {rsi:.1f} (<{oversold:.0f})",
            "timestamp": timestamp,
        }
    return None


def detect_ema_cross(
    symbol: str,
    candles: List[Dict[str, Any]],
    fast: int = EMA_FAST,
    slow: int = EMA_SLOW,
) -> Optional[Dict[str, Any]]:
    """Detect an EMA fast/slow crossover on the last completed candle.

    Compares the EMA(fast) vs EMA(slow) relationship on the last candle
    versus the previous candle. A crossover is detected when the fast EMA
    crosses above (bullish) or below (bearish) the slow EMA.

    Returns a signal dict, or ``None`` when no crossover occurred.
    """
    closes = _closes(candles)
    min_len = slow + 2  # Need at least slow+2 candles for a meaningful cross
    if len(closes) < min_len:
        logger.debug("EMA cross: not enough candles for %s (%d < %d)", symbol, len(closes), min_len)
        return None

    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)

    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return None

    # Compare the relationship on the last two bars.
    fast_prev, fast_curr = ema_fast[-2], ema_fast[-1]
    slow_prev, slow_curr = ema_slow[-2], ema_slow[-1]

    # Bullish cross: fast was below slow, now above.
    was_below = fast_prev <= slow_prev
    now_above = fast_curr > slow_curr
    bullish_cross = was_below and now_above

    # Bearish cross: fast was above slow, now below.
    was_above = fast_prev >= slow_prev
    now_below = fast_curr < slow_curr
    bearish_cross = was_above and now_below

    timestamp = _last_timestamp(candles)

    if bullish_cross:
        return {
            "type": "ema_cross_up",
            "symbol": symbol,
            "value": fast_curr - slow_curr,
            "message": f"🟢 {symbol} EMA{fast} crossed ABOVE EMA{slow} (bullish crossover)",
            "timestamp": timestamp,
        }
    if bearish_cross:
        return {
            "type": "ema_cross_down",
            "symbol": symbol,
            "value": fast_curr - slow_curr,
            "message": f"🔴 {symbol} EMA{fast} crossed BELOW EMA{slow} (bearish crossover)",
            "timestamp": timestamp,
        }
    return None


def detect_volume_spike(
    symbol: str,
    candles: List[Dict[str, Any]],
    multiplier: float = VOLUME_SPIKE_MULTIPLIER,
    window: int = VOLUME_AVG_WINDOW,
) -> Optional[Dict[str, Any]]:
    """Detect a volume spike — current volume exceeds ``multiplier`` × the
    rolling average over the last ``window`` candles.

    Returns a signal dict, or ``None`` when no spike is detected.
    """
    volumes = _volumes(candles)
    if len(volumes) < window + 1:
        logger.debug("Volume spike: not enough candles for %s (%d < %d)", symbol, len(volumes), window + 1)
        return None

    current_vol = volumes[-1]
    avg_vol = sum(volumes[-(window + 1):-1]) / window

    if avg_vol <= 0:
        return None

    ratio = current_vol / avg_vol

    if ratio >= multiplier:
        timestamp = _last_timestamp(candles)
        return {
            "type": "volume_spike",
            "symbol": symbol,
            "value": ratio,
            "message": (
                f"📊 {symbol} volume spike: {current_vol:,.0f} "
                f"is {ratio:.1f}x the {window}-candle average ({avg_vol:,.0f})"
            ),
            "timestamp": timestamp,
        }
    return None


# ── Combined detector ────────────────────────────────────────────────────


def detect_all_signals(
    symbol: str,
    candles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Run all three detectors and return a list of detected signals.

    Convenience wrapper — returns at most 3 signals (one per detector).
    """
    signals: List[Dict[str, Any]] = []

    for detector in (detect_rsi_signals, detect_ema_cross, detect_volume_spike):
        try:
            sig = detector(symbol, candles)
            if sig is not None:
                signals.append(sig)
        except Exception as exc:
            logger.warning(
                "Signal detector %s failed for %s: %s",
                detector.__name__, symbol, exc,
            )

    return signals
