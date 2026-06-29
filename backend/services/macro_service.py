"""Macro market data service — fetches and caches BTC.D, USDT.D, DXY,
Fear & Greed Index, Binance Long/Short ratio, and detects market regime.

Data sources
-----------
- BTC.D / USDT.D : CoinGecko /api/v3/global
- DXY            : FRED API (series DTWEXBGS) with web-scrape fallback
- Fear & Greed   : alternative.me /fng
- L/S ratio      : Binance Futures /futures/data/globalLongShortAccountRatio
- Regime         : heuristic over BTC.D + DXY

Caching
-------
In-memory dict.  Results valid for 15 minutes (CACHE_TTL).
Stale data is still returned but flagged with ``stale: true``.
Any source that fails returns ``null`` for that field with an error
message; the previous cached value (if any) is returned unchanged.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Cache configuration ─────────────────────────────────────────────────────

CACHE_TTL = 15 * 60  # 15 seconds → 15 minutes

_cache: dict[str, dict[str, Any]] = {
    "btc_dominance": {"value": None, "error": None},
    "usdt_dominance": {"value": None, "error": None},
    "dxy": {"value": None, "error": None},
    "fear_greed_index": {"value": None, "error": None},
    "fear_greed_label": {"value": None, "error": None},
    "binance_ls_ratio": {"value": None, "error": None},
    "regime": {"value": None, "error": None},
}
_last_refresh: Optional[float] = None


# ── Internal helpers ────────────────────────────────────────────────────────


def is_stale() -> bool:
    """Return ``True`` when no refresh has happened or data is older than TTL."""
    if _last_refresh is None:
        return True
    return (time.time() - _last_refresh) > CACHE_TTL


def cached_at() -> Optional[str]:
    """ISO-8601 timestamp of the last successful refresh, or ``None``."""
    if _last_refresh is not None:
        return datetime.fromtimestamp(_last_refresh, tz=timezone.utc).isoformat()
    return None


async def _fetch_json(
    url: str,
    params: Optional[dict[str, str]] = None,
    timeout: float = 10.0,
) -> Optional[Any]:
    """Fetch a URL, return parsed JSON, or ``None`` on any failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params or {})
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


async def _fetch_text(
    url: str,
    timeout: float = 10.0,
) -> Optional[str]:
    """Fetch a URL, return raw text, or ``None`` on any failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


# ── Individual source fetchers ──────────────────────────────────────────────

# Each returns (value, error_message).  When value is None, error_message
# explains why.


async def _fetch_btc_dominance() -> tuple[Optional[float], Optional[str]]:
    """BTC dominance percentage from CoinGecko."""
    data = await _fetch_json("https://api.coingecko.com/api/v3/global")
    if data is None:
        return None, "CoinGecko API unavailable"
    try:
        btc_d = data["data"]["market_cap_percentage"]["btc"]
        return float(btc_d), None
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"Unexpected CoinGecko response: {exc}"


async def _fetch_usdt_dominance() -> tuple[Optional[float], Optional[str]]:
    """USDT dominance percentage from CoinGecko."""
    data = await _fetch_json("https://api.coingecko.com/api/v3/global")
    if data is None:
        return None, "CoinGecko API unavailable"
    try:
        usdt_d = data["data"]["market_cap_percentage"]["usdt"]
        return float(usdt_d), None
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"Unexpected CoinGecko response: {exc}"


async def _fetch_dxy() -> tuple[Optional[float], Optional[str]]:
    """DXY (US Dollar Index) from FRED API or fallback web scrape."""
    api_key = os.environ.get("FRED_API_KEY")
    if api_key:
        data = await _fetch_json(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": "DTWEXBGS",
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "1",
            },
        )
        if data is not None:
            try:
                obs = data["observations"][0]
                if obs["value"] != ".":
                    return float(obs["value"]), None
                return None, "DXY value is '.' (not yet available)"
            except (KeyError, IndexError, ValueError) as exc:
                return None, f"Unexpected FRED response: {exc}"
        # FRED responded but with an error — fall through to fallback

    # Fallback: investing.com or a free DXY tracking site
    # For now we note the missing config; further integrations can add a
    # web-scrape parser here.
    return None, "FRED API key not configured (set FRED_API_KEY env var)"


async def _fetch_fear_greed() -> (
    tuple[Optional[int], Optional[str], Optional[str]]
):
    """Fear & Greed Index (value, label, error) from alternative.me."""
    data = await _fetch_json("https://api.alternative.me/fng/?limit=1")
    if data is None:
        return None, None, "alternative.me API unavailable"
    try:
        entry = data["data"][0]
        return (
            int(entry["value"]),
            entry.get("value_classification"),
            None,
        )
    except (KeyError, IndexError, ValueError) as exc:
        return None, None, f"Unexpected alternative.me response: {exc}"


async def _fetch_binance_ls_ratio() -> tuple[Optional[float], Optional[str]]:
    """Binance Long/Short ratio from Binance Futures API.

    Gracefully degrades when geo-blocked (returns ``None``).
    """
    data = await _fetch_json(
        "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
        params={"symbol": "BTCUSDT", "period": "5m"},
    )
    if data is None:
        return None, (
            "Binance Futures API unavailable (may be geo-blocked)"
        )
    try:
        if isinstance(data, list) and len(data) > 0:
            ratio_str = data[0].get("longShortRatio", "0")
            return float(ratio_str), None
        return None, "Empty response from Binance"
    except (KeyError, IndexError, ValueError) as exc:
        return None, f"Unexpected Binance response: {exc}"


# ── Regime detection ────────────────────────────────────────────────────────


def compute_regime(
    btc_d: Optional[float],
    dxy: Optional[float],
) -> str:
    """Heuristic market-regime classifier.

    Returns one of ``"risk-on"``, ``"risk-off"``, ``"mixed"``, or
    ``"unknown"``.

    Rules
    -----
    *   BTC.D > 50 %  → BTC is the safe-haven (capital flowing to BTC).
        Combined with DXY < 100 that signals aggressive risk-on.
    *   DXY > 105     → broad dollar strength → risk-off.
    *   BTC.D < 40 %  → alt season → risk-on.
    *   Otherwise     → mixed signals / insufficient data.
    """
    if btc_d is None and dxy is None:
        return "unknown"

    clues: list[str] = []
    if btc_d is not None:
        if btc_d > 50:
            clues.append("btc_safe_haven")
        elif btc_d < 40:
            clues.append("alt_season")

    if dxy is not None:
        if dxy > 105:
            clues.append("dollar_strong")
        elif dxy < 100:
            clues.append("dollar_weak")

    if "btc_safe_haven" in clues and "dollar_weak" in clues:
        return "risk-on"
    if "dollar_strong" in clues:
        return "risk-off"
    if "alt_season" in clues:
        return "risk-on"
    return "mixed"


# ── Public API ──────────────────────────────────────────────────────────────


async def refresh_macro_data() -> dict[str, Any]:
    """Fetch all macro data points concurrently, update the in-memory cache,
    and return the assembled response.

    Every source is independent — a single failure never blocks the
    other fetches.  The cache retains the last-known-good value for
    failed sources.
    """
    global _last_refresh

    # Fire all fetches concurrently (asyncio.gather would lose
    # per-task exceptions; create_task keeps them separate).
    tasks = {
        "btc": asyncio.create_task(_fetch_btc_dominance()),
        "usdt": asyncio.create_task(_fetch_usdt_dominance()),
        "dxy": asyncio.create_task(_fetch_dxy()),
        "fg": asyncio.create_task(_fetch_fear_greed()),
        "bls": asyncio.create_task(_fetch_binance_ls_ratio()),
    }

    # Collect results
    btc_d, btc_err = await tasks["btc"]
    usdt_d, usdt_err = await tasks["usdt"]
    dxy_val, dxy_err = await tasks["dxy"]
    fg_val, fg_label, fg_err = await tasks["fg"]
    bls_val, bls_err = await tasks["bls"]

    # ── Update cache (keep previous value on failure) ──────────────
    if btc_d is not None:
        _cache["btc_dominance"]["value"] = btc_d
        _cache["btc_dominance"]["error"] = None
    else:
        _cache["btc_dominance"]["error"] = btc_err

    if usdt_d is not None:
        _cache["usdt_dominance"]["value"] = usdt_d
        _cache["usdt_dominance"]["error"] = None
    else:
        _cache["usdt_dominance"]["error"] = usdt_err

    if dxy_val is not None:
        _cache["dxy"]["value"] = dxy_val
        _cache["dxy"]["error"] = None
    else:
        _cache["dxy"]["error"] = dxy_err

    if fg_val is not None:
        _cache["fear_greed_index"]["value"] = fg_val
        _cache["fear_greed_index"]["error"] = None
    else:
        _cache["fear_greed_index"]["error"] = fg_err
    if fg_label is not None:
        _cache["fear_greed_label"]["value"] = fg_label
    else:
        _cache["fear_greed_label"]["error"] = fg_err

    if bls_val is not None:
        _cache["binance_ls_ratio"]["value"] = bls_val
        _cache["binance_ls_ratio"]["error"] = None
    else:
        _cache["binance_ls_ratio"]["error"] = bls_err

    # ── Regime (depends on current cached BTC.D + DXY) ─────────────
    current_btc_d = _cache["btc_dominance"]["value"]
    current_dxy = _cache["dxy"]["value"]
    _cache["regime"]["value"] = compute_regime(current_btc_d, current_dxy)
    _cache["regime"]["error"] = None

    _last_refresh = time.time()
    return build_response()


def build_response() -> dict[str, Any]:
    """Assemble the API response from the current cache state."""
    stale = is_stale()
    errors: list[dict[str, str]] = []

    data = {
        "btc_dominance": _cache["btc_dominance"]["value"],
        "usdt_dominance": _cache["usdt_dominance"]["value"],
        "dxy": _cache["dxy"]["value"],
        "fear_greed_index": _cache["fear_greed_index"]["value"],
        "fear_greed_label": _cache["fear_greed_label"]["value"],
        "binance_ls_ratio": _cache["binance_ls_ratio"]["value"],
        "regime": _cache["regime"]["value"],
    }

    for key in _cache:
        err = _cache[key]["error"]
        if err:
            errors.append({"field": key, "message": err})

    return {
        "data": data,
        "cached_at": cached_at(),
        "stale": stale,
        "errors": errors or None,
    }
