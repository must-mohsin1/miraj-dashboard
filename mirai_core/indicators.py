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


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, pd.Series]:
    """Compute MACD (Moving Average Convergence Divergence).

    Standard EMA-based MACD: subtract the slow EMA from the fast EMA to get
    the MACD line, then EMA-signal the MACD line for the trigger.

    Returns a dict with ``macd``, ``signal``, and ``histogram`` Series,
    all aligned to *close*.  Early values are ``NaN`` until enough data
    is available.
    """
    ema_fast = close.ewm(span=fast, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def compute_volume_profile(
    df: pd.DataFrame,
    num_bins: int = 20,
    price_range: tuple[float, float] | None = None,
) -> dict[str, list]:
    """Compute Volume Profile (VPVR-style horizontal histogram).

    Buckets trades by price level into *num_bins* bins.  Volume in each
    bin is split into buy/sell using the candle direction
    (``close >= open`` → buy, else sell).

    Returns a dict with parallel lists:
        ``price_levels`` — midpoint price of each bin
        ``volumes``      — total volume in each bin
        ``buy_volumes``  — volume from bullish candles per bin
        ``sell_volumes`` — volume from bearish candles per bin
    """
    close = df["Close"]
    open_ = df["Open"]
    volume = df["Volume"]

    if len(close) == 0 or volume.sum() == 0:
        return {"price_levels": [], "volumes": [], "buy_volumes": [], "sell_volumes": []}

    lo = price_range[0] if price_range else float(close.min())
    hi = price_range[1] if price_range else float(close.max())
    if hi <= lo:
        hi = lo + 1.0

    bins = np.linspace(lo, hi, num_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2.0

    # Classify each bar as bullish/bearish
    is_buy = (close >= open_).fillna(False).to_numpy()
    vol = volume.fillna(0).to_numpy()
    prices = close.to_numpy()

    # Digitize prices into bins
    indices = np.digitize(prices, bins, right=False) - 1
    indices = np.clip(indices, 0, num_bins - 1)

    total_vol = np.zeros(num_bins)
    buy_vol = np.zeros(num_bins)
    sell_vol = np.zeros(num_bins)

    np.add.at(total_vol, indices, vol)
    np.add.at(buy_vol, indices, np.where(is_buy, vol, 0.0))
    np.add.at(sell_vol, indices, np.where(~is_buy, vol, 0.0))

    return {
        "price_levels": [round(float(p), 6) for p in bin_centers],
        "volumes": [round(float(v), 6) for v in total_vol],
        "buy_volumes": [round(float(v), 6) for v in buy_vol],
        "sell_volumes": [round(float(v), 6) for v in sell_vol],
    }


def compute_atr(
    df: pd.DataFrame,
    period: int = config.ATR_PERIOD,
) -> pd.Series:
    """Compute Average True Range (ATR) for volatility-based stop placement.

    Uses Wilder's smoothing (exponential MA with alpha=1/period), matching the
    approach used by ``wilder_rsi``.

    Returns a Series aligned to ``df``.  The last value is the most recent ATR.
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(alpha=1.0 / period, min_periods=period).mean()
    return atr


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
    macd = compute_macd(close)
    volume_profile = compute_volume_profile(df)

    return {
        "rsi": rsi,
        "bb": bb,
        "emas": emas,
        "ema_ribbon": ribbon,
        "golden_death_cross": cross,
        "bmsb": bmsb,
        "bb_squeeze": squeeze,
        "macd": macd,
        "volume_profile": volume_profile,
    }
