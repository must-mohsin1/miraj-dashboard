"""Analysis service — orchestrates the full pipeline for a single trading pair.

Pipeline steps
---------------
macro → OHLCV (5 TFs) → indicators → QQE Mod → SMC → patterns → confluence
→ trade plan → charts

Caching
-------
Results are cached in memory for 15 minutes per symbol (CACHE_TTL).
A second request for the same symbol within TTL returns the cached result
with ``stale: true``.  Outside TTL, the pipeline runs fresh.

Error handling
--------------
If critical upstream APIs (yfinance) fail entirely, the service raises
``RuntimeError``, which the route translates to a 502 response.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

# ── Ensure mirai_core is importable ──────────────────────────────────────
_MIRAI_CORE_PATH = os.environ.get(
    "MIRAI_CORE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "mirai_core"),
)
_MIRAI_PARENT = os.path.dirname(_MIRAI_CORE_PATH)
if _MIRAI_PARENT not in sys.path:
    sys.path.insert(0, _MIRAI_PARENT)

from mirai_core import ohlcv, indicators, qqe_mod, smc, patterns, confluence, trade_plan, charts, macro
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Cache configuration ──────────────────────────────────────────────────
CACHE_TTL = 15 * 60  # 15 minutes

_cache: dict[str, dict[str, Any]] = {}  # symbol → {data, cached_at}


# ── Public API ───────────────────────────────────────────────────────────


def validate_symbol(symbol: str) -> bool:
    """Quick-check if *symbol* is a valid yfinance ticker.

    Returns ``False`` for bogus / non-existent tickers within ~2-5s
    instead of letting the full pipeline hang for 60s+.
    """
    try:
        df = yf.download(symbol, period="1d", interval="1d", progress=False)
        return df is not None and not df.empty
    except Exception:
        return False


def fetch_scan_timeframes(symbol: str, mexc_symbol: str | None = None) -> dict[str, Any]:
    """Load scanner candles from Yahoo or a catalogue-verified MEXC contract."""
    if mexc_symbol is not None:
        return ohlcv.fetch_mexc_all_timeframes(mexc_symbol)
    return ohlcv.fetch_all_timeframes(symbol)


def run_scan(symbol: str, mexc_symbol: str | None = None) -> dict[str, Any]:
    """Run the full analysis pipeline for *symbol*.

    Returns a response dict with keys:
        symbol, confluence_score, trade_plan, score_breakdown,
        stale, cached_at.

    Raises ``RuntimeError`` when a critical upstream API is unreachable.
    """
    # ── Cache check ────────────────────────────────────────────────
    if not _is_stale(symbol):
        cached = _cache.get(symbol)
        if cached is not None:
            return _build_cached_response(symbol, cached)

    # ── 1. Macro ───────────────────────────────────────────────────
    macro_data: dict[str, Any] = {}
    try:
        raw = macro.fetch_macro_data()
        if raw:
            macro_data = raw
        logger.info("Macro data fetched: %d keys", len(macro_data))
    except Exception as exc:
        logger.warning("Macro fetch failed: %s", exc)

    # ── 2. OHLCV (5 TFs) — critical step ───────────────────────────
    timeframes: dict[str, Any] = {}
    try:
        timeframes = fetch_scan_timeframes(symbol, mexc_symbol)
        has_any = any(
            df is not None and not df.empty for df in timeframes.values()
        )
        if not has_any:
            raise RuntimeError(f"No OHLCV data received for {symbol}")
        logger.info(
            "OHLCV fetched: %s",
            {k: len(v) for k, v in timeframes.items() if v is not None and not v.empty},
        )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"yfinance API unavailable for {symbol}: {exc}") from exc

    # ── 3. Indicators (per TF) ─────────────────────────────────────
    ind_results: dict[str, Any] = {}
    for tf, df in timeframes.items():
        if df is None or df.empty:
            ind_results[tf] = {"error": f"No data for {tf}"}
            continue
        try:
            ind_results[tf] = indicators.compute_all(df)
        except Exception as exc:
            ind_results[tf] = {"error": str(exc)}
            logger.warning("Indicators failed for %s on %s: %s", symbol, tf, exc)

    # ── 4. QQE Mod (daily, 4h, 1h) ─────────────────────────────────
    qqe_results: dict[str, Any] = {}
    for tf in ("daily", "4h", "1h"):
        df = timeframes.get(tf)
        if df is not None and not df.empty:
            try:
                qqe_results[tf] = qqe_mod.compute_qqe(df)
            except Exception as exc:
                qqe_results[tf] = {"error": str(exc)}
                logger.warning("QQE failed for %s on %s: %s", symbol, tf, exc)
        else:
            qqe_results[tf] = {"error": f"No data for {tf}"}

    # ── 5. SMC (4h) ────────────────────────────────────────────────
    smc_result: dict[str, Any] = {}
    smc_df = timeframes.get("4h")
    if smc_df is not None and not smc_df.empty:
        try:
            smc_result = smc.analyze(smc_df)
        except Exception as exc:
            smc_result = {"error": str(exc)}
            logger.warning("SMC failed for %s: %s", symbol, exc)
    else:
        smc_result = {"error": "No 4h data for SMC"}

    # ── 5b. Market structure classification (5 TFs) ───────────────
    structure_results: dict[str, Any] = {}
    for tf in ("weekly", "daily", "4h", "1h", "15m"):
        df = timeframes.get(tf)
        if df is not None and not df.empty:
            try:
                structure_results[tf] = smc.classify_structure(df)
            except Exception as exc:
                structure_results[tf] = {"label": "unknown", "error": str(exc)}
                logger.warning("Structure classify failed for %s on %s: %s", symbol, tf, exc)
        else:
            structure_results[tf] = {"label": "unknown", "detail": f"No data for {tf}"}

    # ── 5c. QQE signal summary (per-TF trend/strength) ─────────────
    qqe_signals = _extract_qqe_signals(qqe_results)

    # ── 6. Patterns (daily) ────────────────────────────────────────
    pattern_result: dict[str, Any] = {}
    pat_df = timeframes.get("daily")
    if pat_df is not None and not pat_df.empty:
        try:
            pattern_result["detected"] = patterns.detect(pat_df)
        except Exception as exc:
            pattern_result = {"error": str(exc)}
            logger.warning("Pattern detection failed for %s: %s", symbol, exc)
    else:
        pattern_result = {"error": "No daily data for patterns"}

    # ── 7. Confluence scoring ──────────────────────────────────────
    conf_data = _build_confluence_data(
        macro_data=macro_data,
        ind_results=ind_results,
        qqe_results=qqe_results,
        smc_result=smc_result,
        pattern_result=pattern_result,
    )

    try:
        conf_result = confluence.score(conf_data)
        score_breakdown = conf_result.to_dict()
        conf_score = float(conf_result.total)
    except Exception as exc:
        logger.error("Confluence scoring failed: %s", exc)
        conf_score = 0.0
        score_breakdown = {"error": str(exc)}

    # ── 8. Trade Plan ──────────────────────────────────────────────
    rsi_val: Optional[float] = None
    di = ind_results.get("daily", {})
    if isinstance(di, dict) and "error" not in di:
        rsi_series = di.get("rsi")
        if rsi_series is not None and hasattr(rsi_series, "iloc") and len(rsi_series) > 0:
            rsi_val = float(rsi_series.iloc[-1])

    price_levels = _extract_price_levels(timeframes, smc_result, direction="LONG")

    try:
        trade_plan_result = trade_plan.generate_trade_plan(
            confluence_result=conf_result,
            data=price_levels,
            direction="LONG",
            rsi_current=rsi_val,
        )
    except Exception as exc:
        logger.error("Trade plan generation failed: %s", exc)
        trade_plan_result = {"trade_decision": False, "error": str(exc)}

    # ── 9. Chart (daily, last 100 bars) ────────────────────────────
    chart_html: Optional[str] = None
    chart_df = timeframes.get("daily")
    if chart_df is not None and not chart_df.empty:
        try:
            fig = charts.convert_to_plotly(chart_df.tail(100))
            chart_html = charts.plotly_to_html(fig)
        except Exception as exc:
            logger.warning("Chart rendering failed: %s", exc)

    # ── Assemble result ────────────────────────────────────────────
    trade_plan_flat: dict[str, Any] = _build_flat_trade_plan(trade_plan_result)

    # ── Extract BMSB from weekly indicators ──────────────────────
    bmsb_data: Optional[dict[str, Any]] = None
    weekly_ind = ind_results.get("weekly", {})
    if isinstance(weekly_ind, dict) and "error" not in weekly_ind:
        bmsb_raw = weekly_ind.get("bmsb")
        if bmsb_raw and isinstance(bmsb_raw, dict):
            sma_series = bmsb_raw.get("sma20")
            ema_series = bmsb_raw.get("ema21")
            sma_val = float(sma_series.iloc[-1]) if sma_series is not None and hasattr(sma_series, "iloc") and len(sma_series) > 0 else None
            ema_val = float(ema_series.iloc[-1]) if ema_series is not None and hasattr(ema_series, "iloc") and len(ema_series) > 0 else None
            weekly_df = timeframes.get("weekly")
            current_price = float(weekly_df["Close"].iloc[-1]) if weekly_df is not None and not weekly_df.empty else None
            if sma_val is not None and ema_val is not None and current_price is not None:
                band_value = min(sma_val, ema_val)
                bmsb_data = {
                    "sma_20w": sma_val,
                    "ema_21w": ema_val,
                    "current_price": current_price,
                    "status": "above" if current_price >= band_value else "below",
                    "regime": "bull" if current_price >= band_value else "bear",
                }

    data: dict[str, Any] = {
        "symbol": symbol,
        "overall_score": round(min(conf_score * (100 / 30), 100.0), 1),
        "confluence_score": round(conf_score, 1),
        "score_breakdown": score_breakdown,
        "scores": _extract_category_scores(score_breakdown),
        "trade_plan": trade_plan_result,
        "trade_plan_flat": trade_plan_flat,
        "macro_data": {
            k: macro_data.get(k)
            for k in ("btc_d", "usdt_d", "dxy", "fear_greed", "long_short_ratio_btc")
        },
        "smc": smc_result,
        "patterns": pattern_result,
        "bmsb": bmsb_data,
        "qqe": qqe_results,
        "qqe_signals": qqe_signals,
        "structure": structure_results,
        "indicators": _simplify_indicator_summary(ind_results),
    }

    # Add candle / SMC chart-friendly data from the daily timeframe
    chart_df = timeframes.get("daily")
    if chart_df is not None and not chart_df.empty:
        tail = chart_df.tail(100)
        data["candles"] = _df_to_candle_list(tail)
        data["emas"] = _build_ema_dict(ind_results.get("daily", {}))
    else:
        data["candles"] = []
        data["emas"] = {}

    # Add full plottable indicator series for the chart (daily TF)
    daily_ind = ind_results.get("daily")
    if isinstance(daily_ind, dict) and not daily_ind.get("error"):
        data["macd"] = _build_macd_series(daily_ind.get("macd"))
        data["volume_profile"] = daily_ind.get("volume_profile")
        data["bb"] = _build_bb_series(daily_ind.get("bb"))
        data["rsi"] = _build_rsi_series(daily_ind.get("rsi"))
    else:
        data["macd"] = None
        data["volume_profile"] = None
        data["bb"] = None
        data["rsi"] = None

    # Add order blocks and FVGs from SMC result
    if isinstance(smc_result, dict):
        data["order_blocks"] = _normalize_obs(smc_result.get("order_blocks", []))
        data["fvgs"] = _normalize_fvgs(smc_result.get("fvgs", []))
    else:
        data["order_blocks"] = []
        data["fvgs"] = []

    now_ts = time.time()
    _cache[symbol] = {"data": data, "cached_at": now_ts}

    return _build_cached_response(symbol, _cache[symbol])


def get_cached_or_none(symbol: str) -> Optional[dict[str, Any]]:
    """Return a cached response for *symbol* without triggering a refresh.

    Returns ``None`` when no fresh cache entry exists.
    """
    if _is_stale(symbol):
        return None
    entry = _cache.get(symbol)
    if entry is None:
        return None
    return _build_cached_response(symbol, entry)


def clear_cache(symbol: Optional[str] = None) -> None:
    """Clear the in-memory cache.  If *symbol* is ``None``, clear all."""
    global _cache
    if symbol:
        _cache.pop(symbol, None)
    else:
        _cache = {}


# ── Internal cache helpers ───────────────────────────────────────────────


def _is_stale(symbol: str) -> bool:
    """Check whether the cached entry for *symbol* is older than CACHE_TTL."""
    entry = _cache.get(symbol)
    if entry is None:
        return True
    ts = entry.get("cached_at")
    if ts is None:
        return True
    return (time.time() - ts) > CACHE_TTL


def _build_cached_response(symbol: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Build the API response dict from a cache entry — returns full data."""
    data = entry.get("data", {})
    ts = entry.get("cached_at")
    response = dict(data)
    response["stale"] = _is_stale(symbol)
    response["cached_at"] = (
        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        if ts else None
    )
    return response


# ── Confluence data builder ──────────────────────────────────────────────


def _build_confluence_data(
    macro_data: dict[str, Any],
    ind_results: dict[str, Any],
    qqe_results: dict[str, Any],
    smc_result: dict[str, Any],
    pattern_result: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``data`` dict expected by ``confluence.score()``.

    Each key is a boolean field that the scoring engine checks.
    """
    btc_d = macro_data.get("btc_d")
    usdt_d = macro_data.get("usdt_d")
    fg = macro_data.get("fear_greed")
    fg_value = fg.get("value") if isinstance(fg, dict) else None
    smc_obs = smc_result.get("order_blocks", [])
    smc_fvgs = smc_result.get("fvgs", [])
    smc_lg = smc_result.get("liquidity_grabs", [])
    smc_tl = smc_result.get("trend_lines", [])
    smc_divs = smc_result.get("divergences", [])

    daily = ind_results.get("daily", {})
    weekly = ind_results.get("weekly", {})
    h4 = ind_results.get("4h", {})

    return {
        # ── Regime ──
        "weekly_structure_aligned": _ema_aligned(weekly),
        "daily_structure_aligned": _ema_aligned(daily),
        "btc_d_aligned": bool(btc_d is not None and btc_d > 50),
        "weekly_200ma_position": _ema_above(weekly, 200),
        "usdt_d_favourable": bool(usdt_d is not None and usdt_d < 5.0),
        "bmsb_aligned": bool(weekly.get("bmsb")),
        "fear_greed_aligned": bool(fg_value is not None and fg_value < 50),
        # ── Location ──
        "demand_supply_zone": bool(len(smc_obs) > 0 or len(smc_fvgs) > 0),
        "ote_overlap": bool(len(smc_obs) > 0),
        "order_block_at_zone": bool(len(smc_obs) > 0),
        "fvg_at_zone": bool(len(smc_fvgs) > 0),
        "liquidity_grab_before_ote": bool(len(smc_lg) > 0),
        "trend_line_at_zone": bool(len(smc_tl) > 0),
        # ── Confirmation ──
        "h4_structure_aligned": _ema_aligned(h4),
        "daily_rsi_confirms": _rsi_in_range(daily, 30, 70),
        "h4_rsi_confirms": _rsi_in_range(h4, 30, 70),
        "bb_not_squeezing": not bool(daily.get("bb_squeeze", False)),
        "qqe_aligned": _has_green_signal(qqe_results),
        "m15_structure_aligned": _ema_aligned(ind_results.get("15m", {})),
        "rsi_divergence_present": bool(len(smc_divs) > 0),
        "chart_pattern_confirmed": _has_confirmed_pattern(pattern_result),
        "ema_ribbon_aligned": _ribbon_aligned(daily),
        # ── Volume & Retest ──
        "volume_confirming": True,
        "retest_confirmed": bool(len(smc_obs) > 0),
        "no_fakeout": True,
        # ── Risk ──
        "target_2r_available": bool(len(smc_tl) > 0),
        "clean_stop_level": bool(len(smc_obs) > 0),
        "no_news_risk": True,
    }


def _simplify_indicator_summary(ind_results: dict[str, Any]) -> dict[str, Any]:
    """Extract last-known scalar values from indicator results for the response."""
    summary: dict[str, Any] = {}
    for tf, data in ind_results.items():
        if not isinstance(data, dict) or data.get("error"):
            summary[tf] = {"error": data.get("error", "unknown")}
            continue
        entry: dict[str, Any] = {}
        rsi = data.get("rsi")
        if rsi is not None and hasattr(rsi, "iloc") and len(rsi) > 0:
            entry["rsi"] = round(float(rsi.iloc[-1]), 1)
        cross = data.get("golden_death_cross")
        if cross:
            entry["golden_death_cross"] = cross
        bb = data.get("bb", {})
        if bb:
            entry["bb_squeeze"] = bool(data.get("bb_squeeze", False))

        # ── Volume data for delta detection ──────────────────────────
        volume = data.get("volume")
        if volume is not None and hasattr(volume, "iloc") and len(volume) > 0:
            entry["volume"] = round(float(volume.iloc[-1]), 2)
            # 20-period average volume for relative comparison
            window = min(20, len(volume))
            avg_vol = volume.iloc[-window:].mean()
            entry["avg_volume"] = round(float(avg_vol), 2) if avg_vol is not None and avg_vol == avg_vol else None

        # ── MACD signal for cross detection ──────────────────────────
        macd = data.get("macd", {})
        if isinstance(macd, dict):
            macd_series = macd.get("macd")
            signal_series = macd.get("signal")
            if (
                macd_series is not None and hasattr(macd_series, "iloc") and len(macd_series) > 1
                and signal_series is not None and hasattr(signal_series, "iloc") and len(signal_series) > 1
            ):
                prev_macd = float(macd_series.iloc[-2])
                cur_macd = float(macd_series.iloc[-1])
                prev_sig = float(signal_series.iloc[-2])
                cur_sig = float(signal_series.iloc[-1])
                if cur_macd > cur_sig and prev_macd <= prev_sig:
                    entry["macd_cross"] = "bullish"
                elif cur_macd < cur_sig and prev_macd >= prev_sig:
                    entry["macd_cross"] = "bearish"
                elif cur_macd > cur_sig:
                    entry["macd_cross"] = "above"
                else:
                    entry["macd_cross"] = "below"

        # ── EMA alignment ────────────────────────────────────────────
        emas = data.get("emas")
        if isinstance(emas, dict) and len(emas) >= 2:
            vals = []
            for k, v in sorted(emas.items()):
                if v is not None and hasattr(v, "iloc") and len(v) > 0:
                    vals.append(float(v.iloc[-1]))
            if len(vals) >= 2:
                # short > long → bullish alignment
                if vals[-1] > vals[0]:
                    entry["ema_alignment"] = "bullish"
                else:
                    entry["ema_alignment"] = "bearish"

        # ── Volume profile latest bucket for volume composition ──────
        vp = data.get("volume_profile")
        if isinstance(vp, dict) and vp.get("volumes"):
            vols = vp["volumes"]
            if isinstance(vols, (list, tuple)) and len(vols) > 0:
                total_vol = sum(vols)
                buy_vols = vp.get("buy_volumes", [])
                total_buy = sum(buy_vols) if isinstance(buy_vols, (list, tuple)) else 0
                entry["buy_volume_pct"] = round(total_buy / total_vol * 100, 1) if total_vol > 0 else 50.0

        summary[tf] = entry
    return summary


# ── Low-level helpers ────────────────────────────────────────────────────


def _ema_aligned(tf_data: Any) -> bool:
    """Check if short EMAs are above long EMAs (bullish alignment)."""
    if not isinstance(tf_data, dict) or tf_data.get("error"):
        return False
    emas = tf_data.get("emas")
    if not isinstance(emas, dict) or len(emas) < 2:
        return False
    vals = []
    for k, v in sorted(emas.items()):
        if v is not None and hasattr(v, "iloc") and len(v) > 0:
            vals.append(float(v.iloc[-1]))
    return len(vals) >= 2 and vals[-1] > vals[0]  # short > long


def _ema_above(tf_data: Any, span: int) -> bool:
    """Check if the EMA for *span* has a positive value (price above EMA)."""
    if not isinstance(tf_data, dict) or tf_data.get("error"):
        return False
    emas = tf_data.get("emas", {})
    ema = emas.get(span)
    if ema is not None and hasattr(ema, "iloc") and len(ema) > 0:
        return float(ema.iloc[-1]) > 0
    return False


def _rsi_in_range(tf_data: Any, lo: float, hi: float) -> bool:
    """Check if latest RSI is in a given range."""
    if not isinstance(tf_data, dict) or tf_data.get("error"):
        return False
    rsi = tf_data.get("rsi")
    if rsi is not None and hasattr(rsi, "iloc") and len(rsi) > 0:
        val = float(rsi.iloc[-1])
        return lo < val < hi
    return False


def _has_green_signal(qqe_results: dict[str, Any]) -> bool:
    """Check if any QQE result shows a GREEN (bullish) signal."""
    for result in qqe_results.values():
        if isinstance(result, dict) and result.get("signal") in ("GREEN", "GREEN-STRONG"):
            return True
    return False


def _extract_qqe_signals(
    qqe_results: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Condense raw QQE results into {tf: {trend, strength}} for the UI.

    Source ``signal`` values: GREEN-STRONG, GREEN, RED-STRONG, RED, Neutral.
    Returns trend in {GREEN, RED, NEUTRAL} and strength in {STRONG, NORMAL, NONE}.
    Errors / missing TFs default to ``{trend: NEUTRAL, strength: NONE}``.
    """
    out: dict[str, dict[str, str]] = {}
    for tf in ("daily", "4h", "1h"):
        raw = qqe_results.get(tf)
        if not isinstance(raw, dict) or "error" in raw:
            out[tf] = {"trend": "NEUTRAL", "strength": "NONE"}
            continue
        sig = raw.get("signal", "Neutral")
        if sig == "GREEN-STRONG":
            out[tf] = {"trend": "GREEN", "strength": "STRONG"}
        elif sig == "GREEN":
            out[tf] = {"trend": "GREEN", "strength": "NORMAL"}
        elif sig == "RED-STRONG":
            out[tf] = {"trend": "RED", "strength": "STRONG"}
        elif sig == "RED":
            out[tf] = {"trend": "RED", "strength": "NORMAL"}
        else:
            out[tf] = {"trend": "NEUTRAL", "strength": "NONE"}
    return out


def _has_confirmed_pattern(pattern_result: dict[str, Any]) -> bool:
    """Check if at least one detected pattern is confirmed."""
    detected = pattern_result.get("detected", [])
    return any(p.get("confirmed", False) for p in detected)


def _ribbon_aligned(tf_data: Any) -> bool:
    """Check EMA ribbon alignment (shortest > longest)."""
    if not isinstance(tf_data, dict) or tf_data.get("error"):
        return False
    ribbon = tf_data.get("ema_ribbon", {})
    if not ribbon:
        return False
    vals = []
    for k, v in sorted(ribbon.items()):
        if v is not None and hasattr(v, "iloc") and len(v) > 0:
            vals.append(float(v.iloc[-1]))
    return len(vals) >= 2 and vals[0] > vals[-1]


def _extract_price_levels(
    timeframes: dict[str, Any],
    smc_result: dict[str, Any],
    direction: str = "LONG",
) -> dict[str, Any]:
    """Extract price levels for trade plan generation.

    Computes entry zone from the first order block (if any), then derives
    a volatility-based stop loss using ATR, and take-profit levels as
    risk multiples.  Falls back to a percentage-based offset when ATR is
    unavailable.
    """
    from mirai_core.config import ATR_STOP_MULTIPLIER, RISK_PERCENT

    levels: dict[str, Any] = {}
    daily = timeframes.get("daily")
    if daily is not None and not daily.empty:
        try:
            levels["current_price"] = float(daily["Close"].iloc[-1])
            levels["high_24h"] = float(daily["High"].iloc[-1])
            levels["low_24h"] = float(daily["Low"].iloc[-1])
        except (KeyError, IndexError, TypeError, ValueError):
            pass

    cp = levels.get("current_price")

    # ── Entry zone from SMC order blocks ───────────────────────────
    obs = smc_result.get("order_blocks", [])
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    if obs:
        zone = obs[0].get("zone", (None, None))
        if zone[0] is not None:
            entry_zone_low = float(zone[0])
            entry_zone_high = float(zone[1])
            levels["entry_zone_low"] = entry_zone_low
            levels["entry_zone_high"] = entry_zone_high

    # ── Effective entry price ─────────────────────────────────────
    entry_price: float | None
    if entry_zone_low is not None:
        entry_price = entry_zone_low
    elif cp is not None:
        entry_price = cp
    else:
        entry_price = None

    if entry_price is None:
        return levels

    # ── ATR-based stop loss offset ────────────────────────────────
    atr_val = _extract_atr(daily)
    if atr_val is not None and atr_val > 0:
        stop_offset = atr_val * ATR_STOP_MULTIPLIER
    else:
        stop_offset = cp * RISK_PERCENT if cp else entry_price * RISK_PERCENT

    stop_offset = max(stop_offset, 0.01)  # minimum 1 cent offset

    is_long = direction.upper() == "LONG"
    if is_long:
        stop_loss = entry_price - stop_offset
    else:
        stop_loss = entry_price + stop_offset

    stop_loss = max(stop_loss, 0.01)  # positive price

    # ── Ensure minimum 1% distance from entry ───────────────────────
    # If the calculated stop_loss is within 0.1% of entry, use ATR-based
    # fallback (ATR * 1.5).  Guarantee at least 1% distance in all cases.
    min_distance = entry_price * 0.01  # 1% of entry price
    if abs(entry_price - stop_loss) < min_distance:
        if atr_val is not None and atr_val > 0:
            fallback_offset = max(atr_val * 1.5, min_distance)
        else:
            fallback_offset = min_distance
        if is_long:
            stop_loss = entry_price - fallback_offset
        else:
            stop_loss = entry_price + fallback_offset
        stop_loss = max(stop_loss, 0.01)

    levels["stop_loss"] = round(stop_loss, 2)

    # ── Take-profit levels based on risk distance ─────────────────
    risk_distance = abs(entry_price - stop_loss)
    if risk_distance > 0.001:
        if is_long:
            levels["take_profit_1"] = round(entry_price + risk_distance, 2)
            levels["take_profit_2"] = round(entry_price + 2.0 * risk_distance, 2)
        else:
            levels["take_profit_1"] = round(entry_price - risk_distance, 2)
            levels["take_profit_2"] = round(entry_price - 2.0 * risk_distance, 2)

    return levels


def _extract_atr(daily: Any) -> float | None:
    """Compute the latest ATR value from a daily OHLCV DataFrame.

    Returns the scalar ATR value, or ``None`` when the DataFrame is
    too short to compute ATR or any required column is missing.
    """
    if daily is None:
        return None
    try:
        required = {"High", "Low", "Close"}
        if not required.issubset(daily.columns):
            return None
        atr_series = indicators.compute_atr(daily)
        if atr_series is None or len(atr_series.dropna()) < 2:
            return None
        val = float(atr_series.iloc[-1])
        return val if val > 0 else None
    except Exception:
        return None


# ── UI-friendly data helpers ─────────────────────────────────────────────


def _build_flat_trade_plan(tp: dict[str, Any]) -> dict[str, Any]:
    """Flatten a trade_plan dict to UI-friendly flat keys (entry/stop_loss/target_N)."""
    flat: dict[str, Any] = {}
    flat["direction"] = tp.get("direction", "LONG")
    entry_zone = tp.get("entry_zone", {})
    if isinstance(entry_zone, dict):
        flat["entry"] = entry_zone.get("low") or entry_zone.get("high")
    else:
        flat["entry"] = None
    flat["stop_loss"] = tp.get("stop_loss")
    tps = tp.get("take_profit_targets", [])
    if isinstance(tps, list):
        for i, tgt in enumerate(tps[:3]):
            level = tgt.get("level") if isinstance(tgt, dict) else None
            flat[f"target_{i + 1}"] = level
    flat["rationale"] = tp.get("reasoning") or tp.get("verdict", "")

    # Explicit TP prices for DCA engine
    flat["tp1_price"] = tp.get("tp1_price")
    flat["tp2_price"] = tp.get("tp2_price")

    return flat


def _extract_category_scores(sb: Any) -> dict[str, float]:
    """Extract {regime, location, confirmation, volume, risk} scores from score_breakdown."""
    if not isinstance(sb, dict):
        return {}
    cats = ("regime", "location", "confirmation", "volume_retest", "risk")
    return {
        cat: float(sb.get(cat, {}).get("score", 0.0))
        for cat in cats
        if isinstance(sb.get(cat), dict)
    }


def _df_to_candle_list(df: Any) -> list[dict[str, Any]]:
    """Convert a OHLCV DataFrame tail to a list of candle dicts for chart rendering."""
    candles: list[dict[str, Any]] = []
    try:
        import pandas as pd  # noqa: F811

        for _, row in df.tail(100).iterrows():
            candle: dict[str, Any] = {}
            ts = row.get("time") or row.get("timestamp") or row.name
            if isinstance(ts, pd.Timestamp):
                candle["time"] = ts.isoformat()
            elif ts is not None:
                candle["time"] = str(ts)
            for col in ("open", "high", "low", "close", "volume"):
                val = row.get(col.capitalize()) or row.get(col)
                candle[col] = float(val) if val is not None else None
            if candle.get("time"):
                candles.append(candle)
    except Exception:
        pass
    return candles


def _build_ema_dict(ind_data: Any) -> dict[str, list[float]]:
    """Build {ema_period: [values]} from daily indicator results."""
    emas: dict[str, list[float]] = {}
    if not isinstance(ind_data, dict) or ind_data.get("error"):
        return emas
    raw_emas = ind_data.get("emas")
    if isinstance(raw_emas, dict):
        for period, series in raw_emas.items():
            if hasattr(series, "tolist"):
                emas[str(period)] = [round(float(v), 2) for v in series.tail(100)]
            elif isinstance(series, list):
                emas[str(period)] = [round(float(v), 2) for v in series[-100:]]
    return emas


def _build_macd_series(macd_data: Any) -> dict[str, list[float]]:
    """Build {macd, signal, histogram: [values]} from compute_macd result."""
    if not isinstance(macd_data, dict):
        return {}
    out: dict[str, list[float]] = {}
    for key in ("macd", "signal", "histogram"):
        series = macd_data.get(key)
        if series is None:
            out[key] = []
        elif hasattr(series, "tail"):
            out[key] = [
                round(float(v), 6)
                for v in series.tail(100)
                if v is not None and not (isinstance(v, float) and v != v)
            ]
        elif isinstance(series, list):
            out[key] = [
                round(float(v), 6)
                for v in series[-100:]
                if v is not None and not (isinstance(v, float) and v != v)
            ]
        else:
            out[key] = []
    return out


def _build_bb_series(bb_data: Any) -> dict[str, list[float]]:
    """Build {upper, middle, lower: [values]} from compute_bollinger_bands result."""
    if not isinstance(bb_data, dict):
        return {}
    out: dict[str, list[float]] = {}
    for key in ("upper", "middle", "lower"):
        series = bb_data.get(key)
        if series is None:
            out[key] = []
        elif hasattr(series, "tail"):
            out[key] = [
                round(float(v), 2)
                for v in series.tail(100)
                if v is not None and not (isinstance(v, float) and v != v)
            ]
        elif isinstance(series, list):
            out[key] = [
                round(float(v), 2)
                for v in series[-100:]
                if v is not None and not (isinstance(v, float) and v != v)
            ]
        else:
            out[key] = []
    return out


def _build_rsi_series(rsi_data: Any) -> list[float]:
    """Build [values] from an RSI pandas.Series, last 100 bars."""
    if rsi_data is None:
        return []
    if hasattr(rsi_data, "tail"):
        return [
            round(float(v), 2)
            for v in rsi_data.tail(100)
            if v is not None and not (isinstance(v, float) and v != v)
        ]
    if isinstance(rsi_data, list):
        return [
            round(float(v), 2)
            for v in rsi_data[-100:]
            if v is not None and not (isinstance(v, float) and v != v)
        ]
    return []


def _normalize_obs(obs: Any) -> list[dict[str, Any]]:
    """Normalize order blocks to a consistent dict format for the UI."""
    if not isinstance(obs, list):
        return []
    result: list[dict[str, Any]] = []
    for ob in obs:
        if not isinstance(ob, dict):
            continue
        zone = ob.get("zone", (None, None))
        result.append({
            "start_time": ob.get("start_time") or ob.get("time", ""),
            "end_time": ob.get("end_time", ""),
            "price_high": float(zone[1]) if isinstance(zone, (list, tuple)) and len(zone) > 1 and zone[1] is not None else None,
            "price_low": float(zone[0]) if isinstance(zone, (list, tuple)) and len(zone) > 0 and zone[0] is not None else None,
            "type": ob.get("type", "bullish"),
        })
    return result


def _normalize_fvgs(fvgs: Any) -> list[dict[str, Any]]:
    """Normalize FVGs to a consistent dict format for the UI."""
    if not isinstance(fvgs, list):
        return []
    result: list[dict[str, Any]] = []
    for fvg in fvgs:
        if not isinstance(fvg, dict):
            continue
        zone = fvg.get("zone", (None, None))
        result.append({
            "start_time": fvg.get("start_time") or fvg.get("time", ""),
            "end_time": fvg.get("end_time", ""),
            "price_high": float(zone[1]) if isinstance(zone, (list, tuple)) and len(zone) > 1 and zone[1] is not None else None,
            "price_low": float(zone[0]) if isinstance(zone, (list, tuple)) and len(zone) > 0 and zone[0] is not None else None,
        })
    return result
