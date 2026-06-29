"""
Pytest configuration and shared fixtures for mirai_core tests.

Provides cached fixture data via JSON/CSV files in tests/fixtures/.
Tests try live API first with fallback to cached data.
"""
from __future__ import annotations

import json
import os
import pickle
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

# Path to this test directory
TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


def _cached_or_live(
    cache_name: str,
    live_fn,
    force_cache: bool = False,
) -> Any:
    """Fetch from a live function, caching the result to disk.

    Subsequent runs read from cache for speed and reproducibility.

    Args:
        cache_name: Base filename (without extension) for cache.
        live_fn: Callable that returns the data.
        force_cache: If True, raise if cache not found instead of calling live_fn.

    Returns:
        The data (dict, DataFrame, etc.)
    """
    cache_path = FIXTURES_DIR / f"{cache_name}.pkl"
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    if force_cache:
        raise FileNotFoundError(
            f"Fixture cache {cache_path} not found. "
            f"Run tests without force_cache to generate it."
        )

    # Fetch live
    data = live_fn()
    with open(cache_path, "wb") as f:
        pickle.dump(data, f)
    return data


def get_btc_daily_df() -> pd.DataFrame:
    """Get BTC-USD daily OHLCV, cached."""
    import yfinance as yf

    def _live():
        df = yf.download("BTC-USD", period="6mo", interval="1d", progress=False)
        # Flatten MultiIndex
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        df.dropna(how="all", inplace=True)
        return df

    df = _cached_or_live("btc_daily", _live)
    return df


def get_btc_weekly_df() -> pd.DataFrame:
    """Get BTC-USD weekly OHLCV, cached."""
    import yfinance as yf

    def _live():
        df = yf.download("BTC-USD", period="2y", interval="1wk", progress=False)
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        df.dropna(how="all", inplace=True)
        return df

    df = _cached_or_live("btc_weekly", _live)
    return df


def get_btc_4h_df() -> pd.DataFrame:
    """Get BTC-USD 4H OHLCV (via 1H resample), cached."""
    import yfinance as yf
    from mirai_core.ohlcv import flat_df

    def _live():
        h1 = yf.download("BTC-USD", period="2mo", interval="1h", progress=False)
        h1 = flat_df(h1)
        df = h1.resample("4h").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
        )
        df.dropna(how="all", inplace=True)
        return df

    df = _cached_or_live("btc_4h", _live)
    return df


def get_macro_fixture() -> dict[str, Any]:
    """Get cached macro data dict."""
    from mirai_core.macro import fetch_macro_data

    data = _cached_or_live("macro_data", fetch_macro_data)
    return data


def get_synthetic_ohlcv(bars: int = 100) -> pd.DataFrame:
    """Generate synthetic OHLCV data for deterministic tests."""
    np.random.seed(42)
    idx = pd.date_range(start="2024-01-01", periods=bars, freq="D")
    close_arr = 100 + np.cumsum(np.random.randn(bars) * 0.5)
    close = pd.Series(close_arr, index=idx)
    high = close + pd.Series(np.abs(np.random.randn(bars)), index=idx)
    low = close - pd.Series(np.abs(np.random.randn(bars)), index=idx)
    open_p = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(np.random.randint(1000, 10000, bars), index=idx)
    return pd.DataFrame(
        {"Open": open_p, "High": high, "Low": low, "Close": close, "Volume": volume}
    )
