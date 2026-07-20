"""Scan route — one-click full analysis for a single trading pair.

POST /api/v1/scan/{symbol}
    Trigger the full pipeline (macro → OHLCV → indicators → QQE Mod → SMC
    → patterns → confluence → trade plan) and return the result.

    Responses
    --------
    200 — analysis result with confluence score, trade plan, score breakdown.
    400 — invalid symbol (not a valid Yahoo Finance ticker).
    502 — critical upstream API (yfinance / CoinGecko) failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import Analysis, User, WatchlistPair
from backend.obsidian import get_vault_path, is_sync_enabled, sync_scan_result

from backend.realtime.mexc_contracts import classify_market_scope, fetch_mexc_contract_catalogue
from backend.realtime.mexc_stream import to_mexc_symbol
from backend.services.analysis_service import get_cached_or_none, run_scan, validate_symbol
from backend.services.export_service import generate_csv, generate_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["scan"])

#: Validate that a symbol matches supported quote currencies (XXX-USD or
#: XXX-USDT).  This is a fast format check that doesn't hit the network.
#: Symbols like "FOOBAR-USD" pass format validation but fail later in the
#: yfinance existence check — the timeout below prevents indefinite hangs.
_SYMBOL_FORMAT_RE = re.compile(r"^[A-Z0-9]{1,12}-?(USD|USDT)$")

#: Maximum time a single scan is allowed to take before we abort and
#: return an error to the client.  Prevents ccxt/yfinance hangs from
#: blocking the request indefinitely.
SCAN_TIMEOUT_SECONDS = 30


# ── Pydantic response model (defined inline for locality) ────────────────

from pydantic import BaseModel, Field  # noqa: E402


class ScanResponse(BaseModel):
    """Shape of the scan API response — includes UI-friendly fields."""

    symbol: str
    overall_score: Optional[float] = Field(None, ge=0, le=100)
    confluence_score: float = Field(..., ge=0, le=30)
    scores: Optional[dict[str, float]] = None
    trade_plan: dict[str, Any]
    trade_plan_flat: Optional[dict[str, Any]] = None
    # ── Typed verdict contract (state/bias/gates/blockers) — mirai_core.verdict ──
    verdict: Optional[dict[str, Any]] = None
    score_breakdown: dict[str, Any]
    macro_data: Optional[dict[str, Any]] = None
    smc: Optional[dict[str, Any]] = None
    patterns: Optional[dict[str, Any]] = None
    bmsb: Optional[dict[str, Any]] = None
    qqe: Optional[dict[str, Any]] = None
    # ── Per-TF QQE trend/strength summary (daily/4h/1h) built by service ──
    qqe_signals: Optional[dict[str, Any]] = None
    # ── Per-TF market structure (weekly/daily/4h/1h/15m → {label, detail, swings}) ──
    structure: Optional[dict[str, Any]] = None
    indicators: Optional[dict[str, Any]] = None
    candles: Optional[list[dict[str, Any]]] = None
    order_blocks: Optional[list[dict[str, Any]]] = None
    fvgs: Optional[list[dict[str, Any]]] = None
    emas: Optional[dict[str, list[float]]] = None
    # ── Full plottable indicator series (Phase 1 — chart upgrades) ──
    macd: Optional[dict[str, Any]] = None
    volume_profile: Optional[dict[str, Any]] = None
    bb: Optional[dict[str, list[float]]] = None
    rsi: Optional[list[float]] = None
    stale: bool = False
    cached_at: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {
        "symbol": "BTC-USD",
        "confluence_score": 18.5,
        "trade_plan": {"trade_decision": True, "direction": "LONG"},
        "score_breakdown": {"total": 18.5, "trade_decision": True},
        "stale": False,
        "cached_at": "2026-06-29T12:00:00+00:00",
    }}}


class ScanErrorResponse(BaseModel):
    """Error body for 502 responses."""

    detail: str


async def resolve_mexc_scan_symbol(symbol: str) -> str | None:
    """Return an active MEXC contract only when catalogue evidence verifies it."""
    catalogue = await fetch_mexc_contract_catalogue()
    market_scope, normalized = classify_market_scope(symbol, catalogue)
    if market_scope != "mexc_realtime" or normalized is None:
        return None
    return to_mexc_symbol(normalized)


# ── Route ────────────────────────────────────────────────────────────────


@router.post(
    "/scan/{symbol}",
    response_model=ScanResponse,
    responses={
        400: {"model": ScanErrorResponse, "description": "Invalid symbol"},
        502: {"model": ScanErrorResponse},
    },
)
async def scan_symbol(
    symbol: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Run the full analysis pipeline for *symbol* and return the result.

    A second request for the same symbol within 15 minutes returns the
    cached result (with ``stale: true``).
    """
    # Normalise symbol (uppercase, strip whitespace)
    symbol = symbol.strip().upper()

    # ── Validate symbol format (fast, no network) ────────────────────
    # Reject malformed symbols before hitting yfinance so users get an
    # immediate 400 instead of a multi-second hang.
    if not _SYMBOL_FORMAT_RE.match(symbol):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid symbol format: '{symbol}'. Expected XXX-USD or XXX-USDT (e.g. BTC-USD).",
        )

    # ── Validate symbol exists via Yahoo Finance or active MEXC catalogue ──
    mexc_symbol = None
    if not validate_symbol(symbol):
        mexc_symbol = await resolve_mexc_scan_symbol(symbol)
        if mexc_symbol is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid symbol: '{symbol}' is not available from Yahoo Finance or an active MEXC Contract market",
            )

    # ── Check for fresh cache ──────────────────────────────────────
    cached = get_cached_or_none(symbol)
    if cached is not None:
        return cached

    # ── Run pipeline (with 30s timeout to prevent indefinite hangs) ─
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run_scan, symbol, mexc_symbol),
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error("Scan for %s timed out after %ds", symbol, SCAN_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail=f"Scan for '{symbol}' timed out after {SCAN_TIMEOUT_SECONDS}s. The market data service may be unavailable.",
        )
    except RuntimeError as exc:
        # Critical upstream API failure → 502
        logger.error("Scan pipeline failed for %s: %s", symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during scan for %s", symbol)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Analysis service error: {exc}",
        ) from exc

    # ── Persist to analyses table ──────────────────────────────────
    # Persist the FULL scan result dict (not just 3 fields) so the diff
    # endpoint can compare QQE flips, structure changes, patterns, and
    # indicator states across scans. Old rows (pre-A0) only have
    # {confluence_score, trade_plan, score_breakdown} — they still parse,
    # they just won't have the extra fields to diff against.
    try:
        # Extract score from full result for the indexable column
        score_val: float | None = (
            result.get("overall_score") or result.get("confluence_score")
        )
        analysis = Analysis(
            user_id=current_user.id,
            pair=symbol,
            analysis_type="scan",
            score=score_val,
            parameters=json.dumps({"symbol": symbol}),
            # `default=str` guards against non-natively-serializable values
            # (e.g. numpy scalars) from the indicator pipeline.
            result=json.dumps(result, default=str),
        )
        session.add(analysis)
    except Exception as exc:
        logger.warning("Failed to persist analysis result: %s", exc)
        # Non-fatal — result is still returned to the caller

    # ── Sync to Obsidian vault (best-effort) ──────────────────────────
    try:
        vault_path = await get_vault_path(session, current_user.id)
        if vault_path:
            enabled = await is_sync_enabled(session, current_user.id, symbol)
            if enabled:
                await asyncio.to_thread(
                    sync_scan_result,
                    current_user.id, symbol, result, vault_path,
                )
    except Exception as sync_exc:
        logger.warning(
            "Obsidian sync failed for %s (user %d): %s",
            symbol, current_user.id, sync_exc,
        )

    # ── Alert manager (best-effort) ──────────────────────────────────
    try:
        from backend.alerts.manager import process_scan_results

        # Wrap the single scan result into the per-user dict that
        # process_scan_results expects.  The route already normalises
        # the symbol earlier.
        results_by_user = {current_user.id: [{
            "symbol": symbol,
            "confluence_score": result.get("confluence_score", 0),
            "overall_score": result.get("overall_score"),
            "trade_plan": result.get("trade_plan", {}),
        }]}
        await process_scan_results(session, results_by_user)
    except Exception as alert_exc:
        logger.warning(
            "Alert check failed for %s (user %d): %s",
            symbol, current_user.id, alert_exc,
        )

    return result


@router.post(
    "/scan/{symbol}/export",
    responses={
        400: {"model": ScanErrorResponse, "description": "Invalid symbol or format"},
        502: {"model": ScanErrorResponse},
    },
)
async def export_analysis(
    symbol: str,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Export the current analysis for *symbol* as CSV or PDF.

    The pipeline is triggered (or cached result returned) exactly like
    ``scan_symbol``, then the result is serialised into the requested
    format and returned as a file download.
    """
    symbol = symbol.strip().upper()

    # Validate symbol first
    if not validate_symbol(symbol):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid symbol: '{symbol}' is not a valid trading pair on Yahoo Finance",
        )

    # Run (or fetch cached) analysis
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run_scan, symbol),
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error("Export scan for %s timed out after %ds", symbol, SCAN_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail=f"Scan for '{symbol}' timed out after {SCAN_TIMEOUT_SECONDS}s.",
        )
    except RuntimeError as exc:
        logger.error("Export pipeline failed for %s: %s", symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during export for %s", symbol)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Analysis service error: {exc}",
        ) from exc

    # Serialise to requested format
    if format == "csv":
        csv_content = generate_csv(result)
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{symbol}_analysis.csv"',
            },
        )
    else:  # pdf
        pdf_bytes = generate_pdf(result)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{symbol}_analysis.pdf"',
            },
        )


# ── Deep scan (vision analysis) ─────────────────────────────────────────


class DeepScanResponse(ScanResponse):
    """Extended scan result with deep (AI-style) narrative analysis.

    All the regular ``ScanResponse`` fields are present; this model adds
    the ``deep_analysis`` key with a comprehensive textual breakdown.
    """

    deep_analysis: Optional[dict[str, Any]] = None

    model_config = {"json_schema_extra": {"example": {
        "symbol": "BTC-USD",
        "confluence_score": 18.5,
        "deep_analysis": {
            "summary": "Bullish bias (72%) — BTC-USD shows strong bullish alignment...",
            "detailed_analysis": [
                {"heading": "QQE Signal Consensus", "body": "QQE is GREEN across all 3 timeframes..."},
            ],
            "risk_factors": ["QQE conflict: GREEN on daily vs RED on 4h"],
            "key_levels": {"entry": 65000, "stop_loss": 62000, "target_1": 70000},
            "timeframe_breakdown": {"weekly": "RSI 62 (bullish)", "daily": "RSI 55 (neutral) | Structure: HH"},
            "bullish_signals": 8,
            "bearish_signals": 3,
            "neutral_signals": 2,
            "bias_percent": 72,
        },
        "stale": False,
    }}}


@router.post(
    "/scan/{symbol}/deep",
    response_model=DeepScanResponse,
    responses={
        400: {"model": ScanErrorResponse, "description": "Invalid symbol"},
        502: {"model": ScanErrorResponse},
    },
)
async def deep_scan_symbol(
    symbol: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Run a deep scan of *symbol* — bypasses cache and adds narrative analysis.

    The regular scan runs the full pipeline (macro → OHLCV → indicators →
    QQE → SMC → patterns → confluence → trade plan) and caches the result
    for 15 minutes.

    The **deep** scan:
    1. Clears the in-memory cache for this symbol so the result is always fresh.
    2. Runs the identical pipeline.
    3. Generates a comprehensive textual deep analysis covering trend alignment,
       QQE consensus, market structure coherence, pattern implications, volume
       confirmation, key levels, risk factors, and an overall verdict.

    Use this when you want the most up-to-date picture with detailed
    narrative context, especially before making a trading decision.
    """
    from backend.services.deep_analysis_service import generate_deep_analysis

    symbol = symbol.strip().upper()

    # Validate symbol
    if not validate_symbol(symbol):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid symbol: '{symbol}' is not a valid trading pair on Yahoo Finance",
        )

    # ── Clear cache then run fresh ────────────────────────────────
    from backend.services.analysis_service import clear_cache as _clear_cache
    _clear_cache(symbol)

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run_scan, symbol),
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error("Deep scan for %s timed out after %ds", symbol, SCAN_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail=f"Deep scan for '{symbol}' timed out after {SCAN_TIMEOUT_SECONDS}s.",
        )
    except RuntimeError as exc:
        logger.error("Deep scan pipeline failed for %s: %s", symbol, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during deep scan for %s", symbol)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Analysis service error: {exc}",
        ) from exc

    # ── Generate deep analysis narrative ──────────────────────────
    try:
        deep_analysis = generate_deep_analysis(result)
    except Exception as exc:
        logger.warning("Deep analysis generation failed for %s: %s", symbol, exc)
        deep_analysis = {
            "summary": f"Technical data available but narrative generation failed: {exc}",
            "detailed_analysis": [],
            "risk_factors": [],
            "key_levels": {},
            "timeframe_breakdown": {},
            "bullish_signals": 0,
            "bearish_signals": 0,
            "neutral_signals": 0,
            "bias_percent": 50,
        }

    # ── Persist to analyses table ─────────────────────────────────
    try:
        score_val = result.get("overall_score") or result.get("confluence_score")
        analysis = Analysis(
            user_id=current_user.id,
            pair=symbol,
            analysis_type="deep_scan",  # distinguishes from regular scan
            score=score_val,
            parameters=json.dumps({"symbol": symbol}),
            result=json.dumps({**result, "deep_analysis": deep_analysis}, default=str),
        )
        session.add(analysis)
    except Exception as exc:
        logger.warning("Failed to persist deep scan result: %s", exc)

    # ── Sync to Obsidian vault (best-effort) ──────────────────────
    try:
        vault_path = await get_vault_path(session, current_user.id)
        if vault_path:
            enabled = await is_sync_enabled(session, current_user.id, symbol)
            if enabled:
                await asyncio.to_thread(
                    sync_scan_result,
                    current_user.id, symbol, {**result, "deep_analysis": deep_analysis},
                    vault_path,
                )
    except Exception as sync_exc:
        logger.warning("Obsidian sync failed for deep scan %s: %s", symbol, sync_exc)

    # ── Alert manager (best-effort) ───────────────────────────────
    try:
        from backend.alerts.manager import process_scan_results
        results_by_user = {current_user.id: [{
            "symbol": symbol,
            "confluence_score": result.get("confluence_score", 0),
            "overall_score": result.get("overall_score"),
            "trade_plan": result.get("trade_plan", {}),
        }]}
        await process_scan_results(session, results_by_user)
    except Exception as alert_exc:
        logger.warning("Alert check failed for deep scan %s: %s", symbol, alert_exc)

    return {**result, "deep_analysis": deep_analysis}


# ── Batch scan route is defined in routes/watchlist.py ──────────────────