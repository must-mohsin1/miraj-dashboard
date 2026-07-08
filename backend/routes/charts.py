"""Charts route — on-demand OHLCV + indicators by timeframe.

GET /api/v1/charts/{symbol}/candles
    Fetch OHLCV candles for a given timeframe.

    Query params:
        timeframe: one of 1m|5m|15m|1h|4h|1d|1w (default 1d)
        limit:     number of bars to return (default 200, max 1000)

Uses ccxt fetchOHLCV for crypto pairs (no API key required for public
market data) and falls back to yfinance for Yahoo-style tickers.

A separate indicators endpoint can be extended later.  For now MACD,
RSI, Bollinger Bands, and Volume Profile are included in the scan
response, not here.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["charts"])

# ── Timeframe config ──────────────────────────────────────────────────────

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

# ccxt timeframe strings (same spelling for all supported exchanges)
_CCXT_TF: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}

# yfinance (interval, period) mapping
_YF_TF: dict[str, tuple[str, str]] = {
    "1m": ("1m", "5d"),   # yfinance caps 1m at 7d
    "5m": ("5m", "30d"),  # yfinance caps 5m at 60d
    "15m": ("15m", "1mo"),
    "1h": ("1h", "3mo"),
    "4h": ("1h", "6mo"),  # resampled downstream
    "1d": ("1d", "2y"),
    "1w": ("1wk", "5y"),
}

# ── Response models ───────────────────────────────────────────────────────


class DrawingItem(BaseModel):
    """Persisted chart drawing item.

    The backend currently has no drawing persistence.  This model documents
    the forward-compatible shape for future drawing storage while allowing the
    frontend contract to receive a graceful empty state today.
    """

    id: str
    type: str
    points: list[dict[str, Any]] = Field(default_factory=list)
    style: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DrawingsResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    drawings: list[DrawingItem]
    total: int


# ── In-memory cache ───────────────────────────────────────────────────────

_cache: dict[str, dict[str, Any]] = {}


def _cache_ttl(timeframe: str) -> int:
    """Shorter TTL for intraday, longer for higher timeframes."""
    if timeframe in ("1m", "5m", "15m"):
        return 60
    if timeframe in ("1h", "4h"):
        return 120
    return 300  # 1d / 1w


def _get_cached(symbol: str, tf: str) -> list[dict[str, Any]] | None:
    key = f"{symbol}|{tf}"
    entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() - entry["ts"] > _cache_ttl(tf):
        return None
    return entry["data"]


def _set_cached(symbol: str, tf: str, data: list[dict[str, Any]]) -> None:
    key = f"{symbol}|{tf}"
    _cache[key] = {"data": data, "ts": time.time()}


# ── Symbol normalisation ─────────────────────────────────────────────────

# Common Yahoo-style crypto symbols that map to USDT pairs on exchanges
_CRYPTO_TICKERS = {
    "BTC-USD": "BTC/USDT",
    "ETH-USD": "ETH/USDT",
    "SOL-USD": "SOL/USDT",
    "XRP-USD": "XRP/USDT",
    "ADA-USD": "ADA/USDT",
    "DOGE-USD": "DOGE/USDT",
    "BNB-USD": "BNB/USDT",
    "AVAX-USD": "AVAX/USDT",
    "DOT-USD": "DOT/USDT",
    "LINK-USD": "LINK/USDT",
    "MATIC-USD": "MATIC/USDT",
    "LTC-USD": "LTC/USDT",
}

# Known fiat suffixes (non-crypto) that should always use yfinance
_FIAT_SUFFIXES = ("-USD", "=X", "=F")


def _is_crypto(symbol: str) -> bool:
    """Heuristic: is this a crypto pair suitable for ccxt?"""
    upper = symbol.upper()
    # Explicit Yahoo crypto tickers
    if upper in _CRYPTO_TICKERS:
        return True
    # Exchange-style pairs like BTCUSDT, ETHBTC
    if upper.endswith("USDT") or upper.endswith("BUSD") or upper.endswith("BTC"):
        return True
    return False


def _to_ccxt_symbol(symbol: str) -> str:
    """Convert any supported symbol format to a ccxt pair (BASE/QUOTE)."""
    upper = symbol.upper()
    if upper in _CRYPTO_TICKERS:
        return _CRYPTO_TICKERS[upper]
    # BTCUSDT → BTC/USDT
    for quote in ("USDT", "BUSD", "USD"):
        if upper.endswith(quote):
            base = upper[: -len(quote)]
            if base:
                return f"{base}/{quote}"
    # BTC-USD → BTC/USDT (already handled by _CRYPTO_TICKERS, but fallback)
    if upper.endswith("-USD"):
        return f"{upper[:-4]}/USDT"
    return upper


def _to_yfinance_symbol(symbol: str) -> str:
    """Normalise a symbol for yfinance (Yahoo Finance ticker format)."""
    upper = symbol.upper()
    # Already a Yahoo-style ticker (BTC-USD) → keep as-is
    if "-" in upper or "=" in upper:
        return upper
    # BTCUSDT → BTC-USD
    for quote in ("USDT", "BUSD"):
        if upper.endswith(quote):
            return f"{upper[: -len(quote)]}-USD"
    return upper


# ── Fetch helpers ────────────────────────────────────────────────────────


def _fetch_ccxt_ohlcv(symbol: str, tf: str, limit: int) -> list[dict[str, Any]]:
    """Fetch OHLCV from ccxt public market data (no API keys needed)."""
    import ccxt  # noqa: PLC0415

    ccxt_symbol = _to_ccxt_symbol(symbol)
    ccxt_tf = _CCXT_TF[tf]

    # Try exchanges in preference order — public OHLCV works without keys
    errors: list[str] = []
    for exchange_id in ("binance", "mexc", "bybit"):
        try:
            exchange_cls = getattr(ccxt, exchange_id, None)
            if exchange_cls is None:
                continue
            ex = exchange_cls({"enableRateLimit": True})
            ohlcv = ex.fetch_ohlcv(ccxt_symbol, timeframe=ccxt_tf, limit=limit)
            if ohlcv and len(ohlcv) > 0:
                logger.info(
                    "ccxt %s fetched %d %s candles for %s",
                    exchange_id, len(ohlcv), tf, ccxt_symbol,
                )
                return [
                    {
                        "time": int(c[0] / 1000),  # ms → seconds
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]) if len(c) > 5 and c[5] is not None else 0.0,
                    }
                    for c in ohlcv if c and len(c) >= 5
                ]
        except Exception as exc:
            errors.append(f"{exchange_id}: {exc}")
            logger.debug("ccxt %s failed for %s: %s", exchange_id, ccxt_symbol, exc)

    raise RuntimeError("; ".join(errors))


def _fetch_yfinance_ohlcv(symbol: str, tf: str, limit: int) -> list[dict[str, Any]]:
    """Fetch OHLCV via yfinance as a fallback for non-crypto symbols."""
    import pandas as pd  # noqa: PLC0415

    yf_symbol = _to_yfinance_symbol(symbol)
    interval, period = _YF_TF[tf]

    df = _yf_download_safe(yf_symbol, interval, period)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {yf_symbol}@{tf}")

    # Resample 4h from 1h if requested
    if tf == "4h":
        import pandas as _pd

        df = df.resample("4h").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        })
        df.dropna(how="all", inplace=True)

    # Take the last `limit` bars
    df = df.tail(limit)

    candles: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ts = row.name
        t: int | None = None
        if isinstance(ts, pd.Timestamp) and not pd.isna(ts):
            t = int(ts.timestamp())
        elif isinstance(ts, str):
            try:
                t = int(pd.Timestamp(ts).timestamp())
            except Exception:
                continue
        else:
            continue
        if t is None:
            continue
        vol_val = row.get("Volume")
        candle: dict[str, Any] = {
            "time": t,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(vol_val) if pd.notna(vol_val) else 0.0,
        }
        candles.append(candle)

    return candles


def _yf_download_safe(symbol: str, interval: str, period: str):
    """Download via yfinance, flattening MultiIndex columns."""
    import yfinance as yf  # noqa: PLC0415

    df = yf.download(symbol, period=period, interval=interval, progress=False)
    if df is None or df.empty:
        return None
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df.dropna(how="all", inplace=True)
    return df


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/drawings", response_model=DrawingsResponse)
async def get_drawings(
    symbol: str = Query(..., min_length=1, description="Trading pair, e.g. BTC-USD"),
    timeframe: Timeframe = Query("1d", description="1m|5m|15m|1h|4h|1d|1w"),
    current_user: User = Depends(get_current_user),
) -> DrawingsResponse:
    """Return saved chart drawings for a symbol/timeframe.

    Drawing persistence is not implemented yet, but the chart UI calls this
    route. Returning an authenticated empty contract prevents a 404 and gives
    the frontend a graceful empty state until persistence is added.
    """
    _ = current_user
    symbol_norm = symbol.strip().upper()
    return DrawingsResponse(
        symbol=symbol_norm,
        timeframe=timeframe,
        drawings=[],
        total=0,
    )


@router.get("/charts/{symbol}/candles")
async def get_candles(
    symbol: str,
    timeframe: Timeframe = Query("1d", description="1m|5m|15m|1h|4h|1d|1w"),
    limit: int = Query(200, ge=1, le=1000, description="Number of bars (max 1000)"),
    current_user: User = Depends(get_current_user),
) -> Any:
    """Fetch OHLCV candles for *symbol* at the given *timeframe*.

    Dispatches to ccxt for crypto pairs (public endpoint, no keys) and
    falls back to yfinance for Yahoo-style tickers.  Results are cached
    in-memory (60s intraday, 120s 1h/4h, 300s 1d/1w).

    Returns a list of ``{time, open, high, low, close, volume}`` dicts
    sorted ascending by time. ``time`` is in epoch seconds.
    """
    symbol_norm = symbol.strip().upper()

    # ── Cache ────────────────────────────────────────────────────────
    cached = _get_cached(symbol_norm, timeframe)
    if cached is not None:
        return {"symbol": symbol_norm, "timeframe": timeframe, "candles": cached}

    # ── Fetch ────────────────────────────────────────────────────────
    import asyncio

    candle_list: list[dict[str, Any]] = []
    try:
        if _is_crypto(symbol_norm):
            # Try ccxt first, fall back to yfinance
            try:
                candle_list = await asyncio.to_thread(
                    _fetch_ccxt_ohlcv, symbol_norm, timeframe, limit
                )
            except Exception as ccxt_err:
                logger.warning(
                    "ccxt fetch failed for %s@%s (%s), falling back to yfinance",
                    symbol_norm, timeframe, ccxt_err,
                )
                candle_list = await asyncio.to_thread(
                    _fetch_yfinance_ohlcv, symbol_norm, timeframe, limit
                )
        else:
            candle_list = await asyncio.to_thread(
                _fetch_yfinance_ohlcv, symbol_norm, timeframe, limit
            )
    except Exception as exc:
        logger.error("Candle fetch failed for %s@%s: %s", symbol_norm, timeframe, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch OHLCV data: {exc}",
        ) from exc

    if not candle_list:
        return {"symbol": symbol_norm, "timeframe": timeframe, "candles": []}

    # Cache + return
    _set_cached(symbol_norm, timeframe, candle_list)
    return {
        "symbol": symbol_norm,
        "timeframe": timeframe,
        "candles": candle_list,
        "count": len(candle_list),
    }
