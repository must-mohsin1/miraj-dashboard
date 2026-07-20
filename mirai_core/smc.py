"""
SMC (Smart Money Concepts) analysis.

Detects:
- Order Blocks (3-candle method)
- Fair Value Gaps (3-candle imbalance)
- Trend Lines (swing high/low connections)
- RSI Divergences (price vs RSI)
- Liquidity Grabs (sweep of swing low/high + recovery)
- Retest Confirmation
- Touch Points counting
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from mirai_core import config
from mirai_core.indicators import wilder_rsi


def _find_swing_highs(
    series: pd.Series,
    distance: int = config.SWING_DISTANCE,
    prominence_factor: float = config.SWING_PROMINENCE,
) -> np.ndarray:
    """Find swing high points using scipy find_peaks."""
    if len(series) < distance * 2 + 1:
        return np.array([], dtype=int)
    prom = series.std() * prominence_factor
    peaks, _ = find_peaks(series.values, distance=distance, prominence=prom)
    return peaks


def _find_swing_lows(
    series: pd.Series,
    distance: int = config.SWING_DISTANCE,
    prominence_factor: float = config.SWING_PROMINENCE,
) -> np.ndarray:
    """Find swing low points (peaks on inverted series)."""
    return _find_swing_highs(-series, distance, prominence_factor)


def annotate_zones(
    zones: list[dict[str, object]],
    df: pd.DataFrame,
    timeframe: str = "4h",
) -> list[dict[str, object]]:
    """Attach actionability metadata to detected zones, in place.

    Each zone dict gains additive keys — existing keys (``type``, ``zone``,
    ``index``) are never modified:

    - ``timeframe``: scanner timeframe the zone was detected on
    - ``age_bars`` / ``age_days``: how long ago the zone printed
    - ``distance_pct``: signed percent from current price to the nearest
      zone edge (negative = zone below spot, positive = above, 0 = inside)
    - ``direction_match``: ``"bullish"`` | ``"bearish"`` — the trade side
      this zone supports as a pullback entry
    - ``actionable``: True when the zone is correctly positioned and within
      ``config.SMC_ACTIONABLE_PULLBACK`` of spot — the same rule
      ``_extract_price_levels`` applies when selecting entry zones
    - ``reason``: human-readable justification for ``actionable``

    Fields that cannot be computed (missing index, empty df, malformed
    zone) are set to ``None`` rather than omitted, so the schema is stable.
    """
    try:
        current_price: float | None = float(df["Close"].iloc[-1])
        if not np.isfinite(current_price) or current_price <= 0:
            current_price = None
    except Exception:
        current_price = None
    last_ts = df.index[-1] if len(df) else None
    bar_hours = config.TIMEFRAME_BAR_HOURS.get(timeframe)
    max_pullback = config.SMC_ACTIONABLE_PULLBACK

    for z in zones:
        if not isinstance(z, dict):
            continue
        z["timeframe"] = timeframe

        # ── Age relative to the latest bar ─────────────────────────
        age_bars: int | None = None
        age_days: float | None = None
        idx_val = z.get("index")
        if idx_val is not None and len(df):
            try:
                pos = df.index.get_loc(idx_val)
                if isinstance(pos, slice):
                    pos = pos.start
                elif not isinstance(pos, (int, np.integer)):
                    pos = int(np.flatnonzero(pos)[0])
                age_bars = int(len(df) - 1 - int(pos))
            except Exception:
                age_bars = None
        if idx_val is not None and last_ts is not None:
            try:
                age_days = round(
                    float((last_ts - idx_val).total_seconds()) / 86400.0, 2
                )
            except Exception:
                age_days = None
        if age_days is None and age_bars is not None and bar_hours:
            age_days = round(age_bars * bar_hours / 24.0, 2)
        z["age_bars"] = age_bars
        z["age_days"] = age_days

        # ── Trade side this zone supports ──────────────────────────
        type_l = str(z.get("type", "")).lower()
        direction_match = type_l if type_l in ("bullish", "bearish") else None
        z["direction_match"] = direction_match

        # ── Distance from spot + pullback validity ─────────────────
        zone = z.get("zone", (None, None))
        bounds_ok = (
            isinstance(zone, (tuple, list))
            and len(zone) >= 2
            and zone[0] is not None
            and zone[1] is not None
        )
        if not bounds_ok:
            z["distance_pct"] = None
            z["actionable"] = False
            z["reason"] = "zone bounds unavailable"
            continue
        if current_price is None:
            z["distance_pct"] = None
            z["actionable"] = False
            z["reason"] = "current price unavailable — cannot assess the zone"
            continue
        low, high = sorted((float(zone[0]), float(zone[1])))
        if high < current_price:
            distance_pct = (high - current_price) / current_price * 100.0
        elif low > current_price:
            distance_pct = (low - current_price) / current_price * 100.0
        else:
            distance_pct = 0.0
        z["distance_pct"] = round(distance_pct, 4)

        if direction_match is None:
            z["actionable"] = False
            z["reason"] = f"unrecognised zone type {z.get('type')!r}"
            continue

        if direction_match == "bullish":
            correctly_positioned = low <= current_price
            gap = max(0.0, (current_price - high) / current_price)
        else:
            correctly_positioned = high >= current_price
            gap = max(0.0, (low - current_price) / current_price)
        actionable = bool(correctly_positioned and gap <= max_pullback)

        max_pct = max_pullback * 100.0
        if low <= current_price <= high:
            reason = "price is inside the zone"
        elif not correctly_positioned:
            side = "below" if direction_match == "bullish" else "above"
            trade = "long" if direction_match == "bullish" else "short"
            reason = f"price is {side} the zone — not positioned for a {trade} pullback"
        elif actionable:
            reason = (
                f"{abs(distance_pct):.2f}% from price — "
                f"within the {max_pct:g}% pullback range"
            )
        else:
            reason = (
                f"{abs(distance_pct):.2f}% from price — "
                f"beyond the {max_pct:g}% pullback range"
            )
        z["actionable"] = actionable
        z["reason"] = reason

    return zones


def find_order_blocks(
    df: pd.DataFrame,
    lookback: int = config.SMC_LOOKBACK,
    timeframe: str = "4h",
) -> list[dict[str, object]]:
    """Detect Order Blocks using the 3-candle method.

    Returns list of dicts with keys: type, zone (low, high), index, plus
    the actionability metadata documented on ``annotate_zones``.
    """
    data = df.tail(lookback)
    obs: list[dict[str, object]] = []
    for i in range(1, len(data) - 1):
        base = data.iloc[i - 1]
        impulse = data.iloc[i]
        cont = data.iloc[i + 1]
        impulse_body = impulse["Close"] - impulse["Open"]
        base_range = base["High"] - base["Low"]
        if base_range <= 0:
            continue
        if impulse_body > 0 and abs(impulse_body) > base_range * 0.8:
            if cont["Close"] > impulse["Close"]:
                obs.append(
                    {
                        "type": "Bullish",
                        "zone": (base["Low"], base["High"]),
                        "index": data.index[i - 1],
                    }
                )
        elif impulse_body < 0 and abs(impulse_body) > base_range * 0.8:
            if cont["Close"] < impulse["Close"]:
                obs.append(
                    {
                        "type": "Bearish",
                        "zone": (base["Low"], base["High"]),
                        "index": data.index[i - 1],
                    }
                )
    return annotate_zones(obs[-5:], df, timeframe=timeframe)  # last 5


def find_fvgs(
    df: pd.DataFrame,
    lookback: int = config.SMC_LOOKBACK,
    timeframe: str = "4h",
) -> list[dict[str, object]]:
    """Detect Fair Value Gaps (3-candle imbalance).

    Returns list of dicts with keys: type, zone (low, high), index, plus
    the actionability metadata documented on ``annotate_zones``.
    """
    data = df.tail(lookback)
    fvgs: list[dict[str, object]] = []
    for i in range(1, len(data) - 1):
        prev = data.iloc[i - 1]
        nxt = data.iloc[i + 1]
        if prev["High"] < nxt["Low"]:  # Bullish FVG
            fvgs.append(
                {
                    "type": "Bullish",
                    "zone": (prev["High"], nxt["Low"]),
                    "index": data.index[i],
                }
            )
        elif prev["Low"] > nxt["High"]:  # Bearish FVG
            fvgs.append(
                {
                    "type": "Bearish",
                    "zone": (nxt["High"], prev["Low"]),
                    "index": data.index[i],
                }
            )
    return annotate_zones(fvgs[-5:], df, timeframe=timeframe)


def detect_rsi_divergences(
    close: pd.Series,
    rsi_period: int = config.RSI_PERIOD,
) -> list[dict[str, object]]:
    """Detect RSI divergences: bearish (price HH, RSI LH) and bullish (price LL, RSI HL).

    Returns list of dicts with keys: type, description.
    """
    rsi = wilder_rsi(close, rsi_period)
    price_highs = _find_swing_highs(close)
    price_lows = _find_swing_lows(close)
    rsi_highs = _find_swing_highs(rsi)
    rsi_lows = _find_swing_lows(rsi)

    divergences: list[dict[str, object]] = []

    # Bearish divergence: price makes higher high but RSI makes lower high
    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        ph = close.iloc[price_highs[-2:]]
        rh = rsi.iloc[rsi_highs[-2:]]
        if (
            ph.iloc[1] > ph.iloc[0]
            and rh.iloc[1] < rh.iloc[0]
        ):
            divergences.append(
                {
                    "type": "Bearish",
                    "description": (
                        "Price HH but RSI LH — potential reversal down"
                    ),
                }
            )

    # Bullish divergence: price makes lower low but RSI makes higher low
    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        pl = close.iloc[price_lows[-2:]]
        rl = rsi.iloc[rsi_lows[-2:]]
        if (
            pl.iloc[1] < pl.iloc[0]
            and rl.iloc[1] > rl.iloc[0]
        ):
            divergences.append(
                {
                    "type": "Bullish",
                    "description": (
                        "Price LL but RSI HL — potential reversal up"
                    ),
                }
            )

    return divergences


def find_liquidity_grabs(
    df: pd.DataFrame,
    lookback: int = config.SMC_LOOKBACK,
    recovery_bars: int = config.LIQUIDITY_RECOVERY_BARS,
) -> list[dict[str, object]]:
    """Detect liquidity grabs (sweep of swing low/high + quick recovery).

    Returns list of dicts with keys: type, price, sweep_index, description.
    """
    close = df["Close"].tail(lookback)
    high = df["High"].tail(lookback)
    low = df["Low"].tail(lookback)
    swing_highs = _find_swing_highs(close)
    swing_lows = _find_swing_lows(close)

    grabs: list[dict[str, object]] = []

    # Check liquidity grabs below swing lows
    for sl in swing_lows:
        sl_idx = len(close) - lookback + sl if sl < lookback else sl
        if sl < len(close) - recovery_bars - 1:
            sl_price = close.iloc[sl]
            grab_slice = low.iloc[sl + 1 : sl + recovery_bars + 1]
            if len(grab_slice) == 0:
                continue
            if grab_slice.min() < sl_price:
                # Check recovery
                after_grab = close.iloc[sl + 1 : sl + recovery_bars + 1]
                if len(after_grab) and after_grab.max() > sl_price:
                    grabs.append(
                        {
                            "type": "Bullish",
                            "price": float(grab_slice.min()),
                            "sweep_index": df.index[sl],
                            "description": (
                                f"Price swept swing low {sl_price:.2f} "
                                f"then recovered — liquidity grab"
                            ),
                        }
                    )

    # Check liquidity grabs above swing highs
    for sh in swing_highs:
        if sh < len(close) - recovery_bars - 1:
            sh_price = close.iloc[sh]
            grab_slice = high.iloc[sh + 1 : sh + recovery_bars + 1]
            if len(grab_slice) == 0:
                continue
            if grab_slice.max() > sh_price:
                after_grab = close.iloc[sh + 1 : sh + recovery_bars + 1]
                if len(after_grab) and after_grab.min() < sh_price:
                    grabs.append(
                        {
                            "type": "Bearish",
                            "price": float(grab_slice.max()),
                            "sweep_index": df.index[sh],
                            "description": (
                                f"Price swept swing high {sh_price:.2f} "
                                f"then reversed — liquidity grab"
                            ),
                        }
                    )

    return grabs


def find_trend_lines(
    df: pd.DataFrame,
    lookback: int = config.SMC_LOOKBACK,
) -> list[dict[str, object]]:
    """Detect trend lines from last 2 swing highs (resistance) and swing lows (support).

    Returns list of dicts with keys: type, slope, current_value, broken.
    """
    close = df["Close"].tail(lookback)
    idx = np.arange(len(close))

    # Resistance: connect last 2 swing highs
    peaks = _find_swing_highs(close)
    lines: list[dict[str, object]] = []
    if len(peaks) >= 2:
        p1, p2 = peaks[-2], peaks[-1]
        y1, y2 = float(close.iloc[p1]), float(close.iloc[p2])
        if p2 != p1:
            res_slope = (y2 - y1) / (p2 - p1)
            res_current = y2 + res_slope * (len(close) - 1 - p2)
            lines.append(
                {
                    "type": "Resistance",
                    "slope": round(res_slope, 4),
                    "current_value": round(res_current, 2),
                    "broken": bool(float(close.iloc[-1]) > res_current),
                }
            )

    # Support: connect last 2 swing lows
    troughs = _find_swing_lows(close)
    if len(troughs) >= 2:
        t1, t2 = troughs[-2], troughs[-1]
        y1, y2 = float(close.iloc[t1]), float(close.iloc[t2])
        if t2 != t1:
            sup_slope = (y2 - y1) / (t2 - t1)
            sup_current = y2 + sup_slope * (len(close) - 1 - t2)
            lines.append(
                {
                    "type": "Support",
                    "slope": round(sup_slope, 4),
                    "current_value": round(sup_current, 2),
                    "broken": bool(float(close.iloc[-1]) < sup_current),
                }
            )

    return lines


def classify_structure(df: pd.DataFrame) -> dict[str, Any]:
    """Classify the latest market structure (HH/HL/LH/LL) from swing points.

    Uses ``scipy.signal.find_peaks`` (via ``_find_swing_highs`` /
    ``_find_swing_lows``) on the High and Low series to locate confirmed
    swing points, then compares the last two of each to determine whether
    the market is making higher/lower highs and higher/lower lows.

    Args:
        df: OHLCV DataFrame with columns Open, High, Low, Close, Volume.

    Returns:
        A dict with keys:
            - ``label``: one of ``"HH"``, ``"HL"``, ``"LH"``, ``"LL"``,
              ``"Insufficient data"``.
            - ``detail``: human-readable description of the structure.
            - ``swings``: list of ``{type, price, index}`` dicts for the
              most recent swing points.
    """

    # Edge case: too few candles to meaningfully detect swings
    if df is None or len(df) < 4:
        return {
            "label": "Insufficient data",
            "detail": "Fewer than 4 candles available for structure analysis.",
            "swings": [],
        }

    # Detect swing highs (peaks on High series) and swing lows (troughs on Low)
    high_peaks = _find_swing_highs(df["High"])
    low_troughs = _find_swing_lows(df["Low"])

    # Build the consolidated swings list (interleaved, sorted by position)
    swings: list[dict[str, Any]] = []
    for idx in high_peaks:
        swings.append({
            "type": "high",
            "price": float(df["High"].iloc[idx]),
            "index": int(idx),
        })
    for idx in low_troughs:
        swings.append({
            "type": "low",
            "price": float(df["Low"].iloc[idx]),
            "index": int(idx),
        })
    swings.sort(key=lambda s: s["index"])

    # Edge case: need at least 2 swings of some kind to classify
    if len(high_peaks) < 2 and len(low_troughs) < 2:
        return {
            "label": "Insufficient data",
            "detail": "Fewer than 2 swing points detected to classify structure.",
            "swings": swings[-6:],
        }

    # ── Compare last two swing highs → HH or LH ──────────────────────
    high_label = "unknown"
    if len(high_peaks) >= 2:
        prev_high = float(df["High"].iloc[high_peaks[-2]])
        last_high = float(df["High"].iloc[high_peaks[-1]])
        high_label = "HH" if last_high > prev_high else "LH"

    # ── Compare last two swing lows → HL or LL ───────────────────────
    low_label = "unknown"
    if len(low_troughs) >= 2:
        prev_low = float(df["Low"].iloc[low_troughs[-2]])
        last_low = float(df["Low"].iloc[low_troughs[-1]])
        low_label = "HL" if last_low > prev_low else "LL"

    # ── Combine into overall label + detail ──────────────────────────
    if high_label == "HH" and low_label == "HL":
        label = "HH"
        detail = "Price making higher highs and higher lows — bullish trend"
    elif high_label == "LH" and low_label == "LL":
        label = "LL"
        detail = "Price making lower highs and lower lows — bearish trend"
    elif high_label == "HH":
        label = "HH"
        detail = "Price making higher highs — bullish pressure on highs"
    elif high_label == "LH":
        label = "LH"
        detail = "Price making lower highs — bearish pressure on highs"
    elif low_label == "HL":
        label = "HL"
        detail = "Price making higher lows — bullish support building"
    elif low_label == "LL":
        label = "LL"
        detail = "Price making lower lows — bearish pressure on lows"
    else:
        label = "unknown"
        detail = "Unable to classify market structure"

    return {
        "label": label,
        "detail": detail,
        "swings": swings[-6:],
    }


def analyze(
    df: pd.DataFrame,
    timeframe: str = "4h",
) -> dict[str, object]:
    """Run full SMC analysis on a DataFrame and return all detections.

    Returns dict with keys: order_blocks, fvgs, divergences,
    liquidity_grabs, trend_lines. Order blocks and FVGs carry the
    actionability metadata documented on ``annotate_zones``, stamped with
    *timeframe*.
    """
    return {
        "order_blocks": find_order_blocks(df, timeframe=timeframe),
        "fvgs": find_fvgs(df, timeframe=timeframe),
        "divergences": detect_rsi_divergences(df["Close"]),
        "liquidity_grabs": find_liquidity_grabs(df),
        "trend_lines": find_trend_lines(df),
    }
