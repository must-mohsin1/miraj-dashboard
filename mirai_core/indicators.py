"""
Technical indicators for crypto analysis.

Provides RSI (Wilder's), Bollinger Bands, EMAs, EMA Ribbon,
Bull Market Support Band, and Golden/Death Cross detection.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from mirai_core import config


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Wilder's RSI (exponential moving average alpha = 1/period)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def compute_rsi(
    close: pd.Series,
    period: int = config.RSI_PERIOD,
) -> pd.Series:
    """Alias for wilder_rsi."""
    return wilder_rsi(close, period)


def compute_bollinger_bands(
    close: pd.Series,
    period: int = config.BB_PERIOD,
    std_dev: float = config.BB_STD,
) -> dict[str, pd.Series]:
    """Return dict with upper, middle, lower bands and bandwidth."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    bandwidth = 2 * std_dev * std / sma
    return {
        "upper": upper,
        "middle": sma,
        "lower": lower,
        "bandwidth": bandwidth,
    }


def is_bb_squeeze(
    close: pd.Series,
    period: int = config.BB_PERIOD,
    threshold: float = config.BB_SQUEEZE_THRESHOLD,
) -> bool:
    """Check if Bollinger Bands are currently squeezing.

    Squeeze = current bandwidth < threshold * average bandwidth over window.
    """
    bb = compute_bollinger_bands(close, period)
    bw = bb["bandwidth"]
    if len(bw.dropna()) < period:
        return False
    avg_bw = bw.rolling(period).mean()
    latest = bw.iloc[-1]
    avg = avg_bw.iloc[-1]
    return latest < threshold * avg


def compute_emas(
    close: pd.Series,
    spans: list[int] | None = None,
) -> dict[int, pd.Series]:
    """Compute exponential moving averages for given spans."""
    if spans is None:
        spans = [config.EMAS_SHORT, config.EMAS_MEDIUM, config.EMAS_LONG]
    return {s: close.ewm(span=s, min_periods=s).mean() for s in spans}


def detect_golden_death_cross(
    close: pd.Series,
    fast: int = config.EMAS_MEDIUM,
    slow: int = config.EMAS_LONG,
    lookback: int = 3,
) -> str | None:
    """Detect Golden Cross (bullish) or Death Cross (bearish).

    Returns 'golden_cross', 'death_cross', or None.
    """
    ema_fast = close.ewm(span=fast, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, min_periods=slow).mean()
    diff = ema_fast - ema_slow
    # check last `lookback` bars for a crossover
    for i in range(-lookback, 0):
        if abs(i) >= len(diff):
            continue
        if diff.iloc[i] > 0 and diff.iloc[i - 1] <= 0:
            return "golden_cross"
        if diff.iloc[i] < 0 and diff.iloc[i - 1] >= 0:
            return "death_cross"
    return None


def compute_ema_ribbon(
    close: pd.Series,
    spans: list[int] | None = None,
) -> dict[int, pd.Series]:
    """Compute the EMA Ribbon (20,25,30,35,40,45,50,55 by default)."""
    if spans is None:
        spans = config.EMA_RIBBON_SPANS
    return compute_emas(close, spans)


def bull_market_support_band(
    close: pd.Series,
) -> dict[str, pd.Series]:
    """Compute Bull Market Support Band (20-week SMA + 21-week EMA).

    For BTC weekly data only.
    """
    sma20 = close.rolling(20).mean()
    ema21 = close.ewm(span=21, min_periods=21).mean()
    return {"sma20": sma20, "ema21": ema21}


def compute_all(
    df: pd.DataFrame,
) -> dict[str, object]:
    """Compute every indicator on a DataFrame with Open, High, Low, Close, Volume.

    Returns a dict keyed by indicator name.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    rsi = compute_rsi(close)
    bb = compute_bollinger_bands(close)
    emas = compute_emas(close)
    ribbon = compute_ema_ribbon(close)
    cross = detect_golden_death_cross(close)
    bmsb = bull_market_support_band(close)
    squeeze = is_bb_squeeze(close)

    return {
        "rsi": rsi,
        "bb": bb,
        "emas": emas,
        "ema_ribbon": ribbon,
        "golden_death_cross": cross,
        "bmsb": bmsb,
        "bb_squeeze": squeeze,
    }
