"""
OHLCV data fetching via yfinance with multi-timeframe support.

Handles yfinance's MultiIndex columns transparently via the flat_df helper.
For 4H: downloads 1H data and resamples.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


# ── helpers ────────────────────────────────────────────────────────────────

def flat_df(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance MultiIndex columns for single-ticker downloads."""
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


# ── public API ─────────────────────────────────────────────────────────────

def fetch_ohlcv(
    symbol: str = "BTC-USD",
    period: str = "6mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """Download OHLCV data for one symbol and flatten columns.

    Args:
        symbol:    Yahoo Finance ticker (e.g. BTC-USD, DX-Y.NYB).
        period:    Valid yfinance period string.
        interval:  Valid yfinance interval string.

    Returns:
        DataFrame with columns Open, High, Low, Close, Volume.
    """
    df = yf.download(symbol, period=period, interval=interval, progress=False)
    if df.empty:
        return pd.DataFrame()
    df = flat_df(df)
    df.dropna(how="all", inplace=True)
    return df


def fetch_weekly(symbol: str = "BTC-USD", years: int = 2) -> pd.DataFrame:
    """Fetch weekly OHLCV for *years* lookback."""
    periods = {1: "1y", 2: "2y", 3: "3y", 5: "5y", 10: "10y"}
    p = periods.get(years, "2y")
    return fetch_ohlcv(symbol, period=p, interval="1wk")


def fetch_daily(symbol: str = "BTC-USD", months: int = 6) -> pd.DataFrame:
    """Fetch daily OHLCV for *months* lookback."""
    periods = {1: "1mo", 3: "3mo", 6: "6mo", 9: "9mo", 12: "1y", 18: "18mo"}
    p = periods.get(months, "6mo")
    return fetch_ohlcv(symbol, period=p, interval="1d")


def fetch_hourly(
    symbol: str = "BTC-USD", days: int = 60
) -> pd.DataFrame:
    """Fetch 1-hour OHLCV for *days* lookback."""
    periods = {7: "7d", 14: "14d", 30: "1mo", 60: "2mo", 90: "3mo"}
    p = periods.get(days, "2mo")
    return fetch_ohlcv(symbol, period=p, interval="1h")


def fetch_15min(symbol: str = "BTC-USD", days: int = 30) -> pd.DataFrame:
    """Fetch 15-min OHLCV for *days* lookback."""
    periods = {7: "7d", 14: "14d", 30: "1mo"}
    p = periods.get(days, "1mo")
    return fetch_ohlcv(symbol, period=p, interval="15m")


def fetch_4h(
    symbol: str = "BTC-USD", days: int = 60
) -> pd.DataFrame:
    """Fetch 4-hour OHLCV by resampling 1-hour data."""
    h1 = fetch_hourly(symbol, days=days)
    if h1.empty:
        return h1
    resampled = h1.resample("4h").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    resampled.dropna(how="all", inplace=True)
    return resampled


def fetch_all_timeframes(
    symbol: str = "BTC-USD",
) -> dict[str, pd.DataFrame]:
    """Return dict of {tf: df} for all 5 core timeframes.

    Keys: weekly, daily, 4h, 1h, 15m.
    """
    return {
        "weekly": fetch_weekly(symbol),
        "daily": fetch_daily(symbol),
        "4h": fetch_4h(symbol),
        "1h": fetch_hourly(symbol),
        "15m": fetch_15min(symbol),
    }
