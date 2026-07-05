"""
QQE Mod — Qualitative Quantitative Estimation with volume-weighted signals.

Exact formula:
1. RSI (Wilder's, 14 period)
2. Smooth RSI (Wilder's, 5 period)
3. Delta = abs(change in smoothed RSI)
4. Smoothed delta (Wilder's, 5 period)
5. Dynamic trailing stop: trail distance = 4.236 * smoothed_delta
6. Track long_stop / short_stop; flip trend on crossover
7. QQE line = smoothed RSI; QQE trailing = active stop
8. Histogram = QQE line - trailing
9. Volume-weighted enhancement: GREEN-STRONG / RED-STRONG
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from mirai_core import config
from mirai_core.indicators import wilder_rsi


def compute_qqe(
    df: pd.DataFrame,
    rsi_period: int = config.QQE_RSI_PERIOD,
    smooth: int = config.QQE_SMOOTH,
    sf: float = config.QQE_SF,
) -> dict[str, Any]:
    """Compute QQE Mod with volume-weighted signals.

    Args:
        df: DataFrame with columns Open, High, Low, Close, Volume.
        rsi_period: RSI period (default 14).
        smooth: Wilder's smoothing period (default 5).
        sf: Safety factor for trailing stop distance (default 4.236).

    Returns:
        dict with qqe_line, qqe_trailing, trend, histogram,
        vol_buying_pct, signal, bars, trend_history.
    """
    close = df["Close"].values
    volume = df["Volume"].values
    opens = df["Open"].values
    n = len(df)

    # Step 1-2: RSI → smoothed RSI
    rsi = wilder_rsi(df["Close"], rsi_period).values
    rsi_s = pd.Series(rsi).ewm(alpha=1.0 / smooth, min_periods=smooth).mean().values

    # Step 3-4: Delta → smoothed delta
    rsi_delta = np.abs(np.diff(rsi_s, prepend=np.nan))
    sd = pd.Series(rsi_delta).ewm(alpha=1.0 / smooth, min_periods=smooth).mean().values

    # Step 5-6: Dynamic trailing stop
    long_stop = np.full(n, np.nan)
    short_stop = np.full(n, np.nan)
    trend = np.zeros(n, dtype=int)

    first_valid: int | None = None
    for i in range(n):
        if not np.isnan(rsi_s[i]) and not np.isnan(sd[i]):
            first_valid = i
            break

    if first_valid is None or first_valid >= n:
        return {"error": "no valid data"}

    long_stop[first_valid] = rsi_s[first_valid] - sf * sd[first_valid]
    short_stop[first_valid] = rsi_s[first_valid] + sf * sd[first_valid]
    trend[first_valid] = 1

    for i in range(first_valid + 1, n):
        if np.isnan(rsi_s[i]) or np.isnan(sd[i]):
            trend[i] = trend[i - 1]
            long_stop[i] = long_stop[i - 1]
            short_stop[i] = short_stop[i - 1]
            continue

        trail = sf * sd[i]
        trend[i] = trend[i - 1]
        long_stop[i] = long_stop[i - 1]
        short_stop[i] = short_stop[i - 1]

        new_long = rsi_s[i] - trail
        new_short = rsi_s[i] + trail

        if trend[i - 1] == 1:
            if rsi_s[i] < long_stop[i]:
                trend[i] = -1
                short_stop[i] = new_short
            else:
                long_stop[i] = max(long_stop[i], new_long)
        else:
            if rsi_s[i] > short_stop[i]:
                trend[i] = 1
                long_stop[i] = new_long
            else:
                short_stop[i] = min(short_stop[i], new_short)

    # Steps 7-8: QQE line and trailing
    qqe_trail = np.where(trend == 1, long_stop, short_stop)
    hist = rsi_s - qqe_trail

    # Volume pressure
    vol_buy = np.where(close > opens, volume, 0.0)
    vol_sell = np.where(close <= opens, volume, 0.0)
    vol_buy_s = pd.Series(vol_buy).rolling(5).sum().values
    vol_sell_s = pd.Series(vol_sell).rolling(5).sum().values
    # Guard against divide-by-zero when both buy and sell volumes are 0
    total_vol = vol_buy_s + vol_sell_s
    vol_ratio = np.where(
        total_vol > 0,
        np.nan_to_num(vol_buy_s / np.where(total_vol > 0, total_vol, 1)),
        0.5,
    )

    last = n - 1
    last_trend = int(trend[last])
    last_hist = float(hist[last]) if not np.isnan(hist[last]) else None
    last_vol = float(vol_ratio[last]) if not np.isnan(vol_ratio[last]) else None

    # Last 10 bar colours
    bar_colors: list[str] = []
    for i in range(max(0, n - 10), n):
        t = int(trend[i])
        v = float(vol_ratio[i]) if not np.isnan(vol_ratio[i]) else 0.5
        if t == 1 and v > config.QQE_VOL_BUY_HIGH:
            bar_colors.append("GREEN-STRONG")
        elif t == 1:
            bar_colors.append("GREEN")
        elif t == -1 and v < config.QQE_VOL_SELL_LOW:
            bar_colors.append("RED-STRONG")
        else:
            bar_colors.append("RED")

    # Determine signal string
    if last_trend == 1:
        signal = (
            "GREEN-STRONG"
            if last_vol is not None and last_vol > config.QQE_VOL_BUY_HIGH
            else "GREEN"
        )
    elif last_trend == -1:
        signal = (
            "RED-STRONG"
            if last_vol is not None and last_vol < config.QQE_VOL_SELL_LOW
            else "RED"
        )
    else:
        signal = "Neutral"

    return {
        "qqe_line": (
            round(float(rsi_s[last]), 2) if not np.isnan(rsi_s[last]) else None
        ),
        "qqe_trailing": (
            round(float(qqe_trail[last]), 2)
            if not np.isnan(qqe_trail[last])
            else None
        ),
        "trend": (
            "BULLISH" if last_trend == 1 else "BEARISH" if last_trend == -1 else "Neutral"
        ),
        "histogram": round(last_hist, 2) if last_hist is not None else None,
        "vol_buying_pct": (
            round(last_vol * 100, 1) if last_vol is not None else None
        ),
        "signal": signal,
        "bars": bar_colors,
        "trend_history": [
            int(t) if not np.isnan(t) else 0 for t in trend[-20:]
        ],
    }
