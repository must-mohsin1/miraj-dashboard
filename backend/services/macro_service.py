"""Macro market data service — fetches and caches BTC.D, USDT.D, DXY,
Fear & Greed Index, Binance Long/Short ratio, and detects market regime.

Data sources
-----------
- BTC.D / USDT.D : CoinGecko /api/v3/global
- DXY            : FRED API (series DTWEXBGS) with web-scrape fallback
- Fear & Greed   : alternative.me /fng
- L/S ratio      : Binance Futures /futures/data/globalLongShortAccountRatio
- Funding rates  : Binance Futures /fapi/v1/premiumIndex (BTC/ETH/SOL)
- CME gaps       : yfinance BTC=F weekly candles (unfilled-gap detection)
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
    "funding_rates": {"value": None, "error": None},
    "cme_gaps": {"value": None, "error": None},
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
    retries: int = 3,
) -> Optional[Any]:
    """Fetch a URL with retry/backoff for rate limiting (429), return parsed JSON or None."""
    import asyncio as _asyncio
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, params=params or {})
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Rate limited (429) on %s, retrying in %ds (attempt %d/%d)", url, wait, attempt + 1, retries)
                    await _asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("Fetch failed for %s: %s, retrying in %ds", url, exc, wait)
                await _asyncio.sleep(wait)
            else:
                logger.warning("Failed to fetch %s after %d attempts: %s", url, retries, exc)
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
    """DXY (US Dollar Index) from FRED API, with yfinance fallback.

    Tries FRED API first (requires ``FRED_API_KEY``).  If the key is not
    set or FRED fails, falls back to yfinance ``DX-Y.NYB`` which needs no
    API key.  This ensures DXY always shows on the dashboard even without
    a FRED key.
    """
    # ── Attempt 1: FRED API (if key is set) ──────────────────────
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
            except (KeyError, IndexError, ValueError) as exc:
                logger.warning("FRED DXY parse error: %s", exc)
        # FRED failed — fall through to yfinance

    # ── Attempt 2: yfinance fallback (no API key needed) ─────────
    try:
        dxy_val = await asyncio.to_thread(_download_dxy)
        if dxy_val is not None:
            return dxy_val, None
        return None, "yfinance returned no DXY data"
    except Exception as exc:
        logger.warning("yfinance DXY fallback failed: %s", exc)
        return None, f"DXY unavailable (FRED key not set and yfinance failed: {exc})"


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


# Binance Futures symbols → display symbol mapping for funding rates.
_FUNDING_SYMBOLS: dict[str, str] = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
}


async def _fetch_funding_rates() -> (
    tuple[Optional[list[dict[str, Any]]], Optional[str]]
):
    """Fetch BTC/ETH/SOL funding rates from Binance Futures ``premiumIndex``.

    The endpoint returns one entry per requested symbol with a
    ``lastFundingRate`` field (a string, e.g. ``"0.0001"`` for a 0.01% rate
    per 8h).  We convert the raw fraction into both the raw rate and a
    human-readable percentage.  Negative funding = shorts paying longs
    (bullish), positive funding = longs paying shorts (overheated).

    A single Binance ``GET /fapi/v1/premiumIndex`` call without a
    ``symbol`` parameter returns *all* symbols; this is rate-friendly and
    much lighter than one call per symbol.
    """
    data = await _fetch_json(
        "https://fapi.binance.com/fapi/v1/premiumIndex",
    )
    if data is None:
        return None, "Binance Futures API unavailable (may be geo-blocked)"
    try:
        if not isinstance(data, list) or len(data) == 0:
            return None, "Empty response from Binance premiumIndex"

        # Build a {binance_symbol: rate} lookup from the response list.
        rate_by_symbol: dict[str, float] = {}
        for item in data:
            sym = item.get("symbol")
            if sym in _FUNDING_SYMBOLS:
                rate_str = item.get("lastFundingRate", "0")
                rate_by_symbol[sym] = float(rate_str)

        results: list[dict[str, Any]] = []
        for binance_symbol, display_symbol in _FUNDING_SYMBOLS.items():
            rate = rate_by_symbol.get(binance_symbol)
            if rate is None:
                continue
            results.append(
                {
                    "symbol": display_symbol,
                    "funding_rate": rate,
                    "funding_rate_percent": round(rate * 100, 5),
                }
            )

        if not results:
            return None, "No funding rates found for BTC/ETH/SOL"
        return results, None
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"Unexpected Binance premiumIndex response: {exc}"


async def _fetch_cme_gaps() -> (
    tuple[Optional[list[dict[str, Any]]], Optional[str]]
):
    """Detect unfilled CME gaps from BTC weekly candles via yfinance.

    CME BTC futures (``BTC=F``) close Friday ~17:00 ET and reopen Sunday
    ~18:00 ET.  A *gap* forms when the new week's open differs from the
    previous week's close by more than a small threshold (0.5% here, to
    avoid flagging trivial tick-level differences).  An *unfilled* gap is
    one where price has not since traded back through the gap zone (the
    band between the prior close and the new open).

    Returns a list of ``{date, gap_percent, direction, filled}`` entries
    for the last ~3 months.  ``direction`` is ``"up"`` when the new open is
    higher than the prior close, ``"down"`` otherwise.
    """
    # yfinance is a blocking, sync library — run it in a worker thread so
    # the async event loop (and concurrent macro fetches) never stalls.
    try:
        df = await asyncio.to_thread(
            _download_cme_weekly,
        )
    except Exception as exc:  # pragma: no cover - network / yfinance errors
        return None, f"yfinance unavailable for BTC=F: {exc}"

    if df is None or df.empty:
        return None, "No BTC=F weekly data from yfinance"

    try:
        rows = list(df.itertuples(index=True))
        if len(rows) < 2:
            return [], None

        gaps: list[dict[str, Any]] = []
        n = len(rows)
        for i in range(1, n):
            prev_row = rows[i - 1]
            curr_row = rows[i]

            prev_close_raw = getattr(prev_row, "Close", None)
            curr_open_raw = getattr(curr_row, "Open", None)
            if prev_close_raw is None or curr_open_raw is None:
                continue
            prev_close = float(prev_close_raw)
            curr_open = float(curr_open_raw)
            if prev_close <= 0 or curr_open <= 0:
                continue

            gap_pct = ((curr_open - prev_close) / prev_close) * 100.0
            if abs(gap_pct) < 0.5:
                continue  # ignore trivial gaps

            direction = "up" if gap_pct > 0 else "down"
            # Gap zone: band between prev_close and curr_open.
            gap_low = min(prev_close, curr_open)
            gap_high = max(prev_close, curr_open)

            filled = False
            for j in range(i + 1, n):
                future_row = rows[j]
                low_raw = getattr(future_row, "Low", None)
                high_raw = getattr(future_row, "High", None)
                if low_raw is None or high_raw is None:
                    continue
                low = float(low_raw)
                high = float(high_raw)
                if low <= gap_high and high >= gap_low:
                    filled = True
                    break

            date_idx = getattr(curr_row, "Index", None)
            if date_idx is not None and hasattr(date_idx, "strftime"):
                date_str = date_idx.strftime("%Y-%m-%d")
            else:
                date_str = str(date_idx)[:10]

            gaps.append(
                {
                    "date": date_str,
                    "gap_percent": round(gap_pct, 2),
                    "direction": direction,
                    "filled": filled,
                }
            )

        # Surface only unfilled gaps (most actionable); keep most-recent first.
        unfilled = [g for g in reversed(gaps) if not g["filled"]]
        return unfilled, None
    except (AttributeError, TypeError, ValueError) as exc:
        return None, f"Failed to parse BTC=F weekly candles: {exc}"


def _download_cme_weekly():
    """Download BTC=F weekly candles (blocking) with flattened columns.

    Imported lazily so the module still imports cleanly in environments
    without yfinance (the route returns a graceful error instead).
    """
    import yfinance as yf  # noqa: PLC0415

    df = yf.download("BTC=F", interval="1wk", period="3mo", progress=False)
    if df is None or df.empty:
        return df
    # Flatten yfinance MultiIndex columns (single-ticker download).
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df.dropna(how="all", inplace=True)
    return df


def _download_dxy() -> Optional[float]:
    """Download DXY (DX-Y.NYB) latest close via yfinance (blocking).

    Used as a fallback when FRED_API_KEY is not set or FRED is unreachable.
    """
    import yfinance as yf  # noqa: PLC0415

    df = yf.download("DX-Y.NYB", period="5d", interval="1d", progress=False)
    if df is None or df.empty:
        return None
    # Flatten yfinance MultiIndex columns (single-ticker download).
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df.dropna(how="all", inplace=True)
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


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
        "fr": asyncio.create_task(_fetch_funding_rates()),
        "cme": asyncio.create_task(_fetch_cme_gaps()),
    }

    # Collect results
    btc_d, btc_err = await tasks["btc"]
    usdt_d, usdt_err = await tasks["usdt"]
    dxy_val, dxy_err = await tasks["dxy"]
    fg_val, fg_label, fg_err = await tasks["fg"]
    bls_val, bls_err = await tasks["bls"]
    fr_val, fr_err = await tasks["fr"]
    cme_val, cme_err = await tasks["cme"]

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

    if fr_val is not None:
        _cache["funding_rates"]["value"] = fr_val
        _cache["funding_rates"]["error"] = None
    else:
        _cache["funding_rates"]["error"] = fr_err

    if cme_val is not None:
        _cache["cme_gaps"]["value"] = cme_val
        _cache["cme_gaps"]["error"] = None
    else:
        _cache["cme_gaps"]["error"] = cme_err

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

    dxy_val = _cache["dxy"]["value"]
    dxy_err = _cache["dxy"]["error"]

    data = {
        "btc_dominance": _cache["btc_dominance"]["value"],
        "usdt_dominance": _cache["usdt_dominance"]["value"],
        "dxy": dxy_val,
        "dxy_error": dxy_err if dxy_val is None else None,
        "fear_greed_index": _cache["fear_greed_index"]["value"],
        "fear_greed_label": _cache["fear_greed_label"]["value"],
        "binance_ls_ratio": _cache["binance_ls_ratio"]["value"],
        "funding_rates": _cache["funding_rates"]["value"],
        "cme_gaps": _cache["cme_gaps"]["value"],
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
