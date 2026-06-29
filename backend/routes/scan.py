"""Scan route — one-click full analysis for a single trading pair.

POST /api/v1/scan/{symbol}
    Trigger the full pipeline (macro → OHLCV → indicators → QQE Mod → SMC
    → patterns → confluence → trade plan) and return the result.

    Responses
    --------
    200 — analysis result with confluence score, trade plan, score breakdown.
    502 — critical upstream API (yfinance / CoinGecko) failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import Analysis, User, WatchlistPair
from backend.obsidian import get_vault_path, is_sync_enabled, sync_scan_result

from backend.services.analysis_service import get_cached_or_none, run_scan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["scan"])


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
    score_breakdown: dict[str, Any]
    macro_data: Optional[dict[str, Any]] = None
    smc: Optional[dict[str, Any]] = None
    patterns: Optional[dict[str, Any]] = None
    qqe: Optional[dict[str, Any]] = None
    indicators: Optional[dict[str, Any]] = None
    candles: Optional[list[dict[str, Any]]] = None
    order_blocks: Optional[list[dict[str, Any]]] = None
    fvgs: Optional[list[dict[str, Any]]] = None
    emas: Optional[dict[str, list[float]]] = None
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


# ── Route ────────────────────────────────────────────────────────────────


@router.post(
    "/scan/{symbol}",
    response_model=ScanResponse,
    responses={502: {"model": ScanErrorResponse}},
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

    # ── Check for fresh cache ──────────────────────────────────────
    cached = get_cached_or_none(symbol)
    if cached is not None:
        return cached

    # ── Run pipeline ───────────────────────────────────────────────
    try:
        result = await asyncio.to_thread(run_scan, symbol)
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
            result=json.dumps({
                "confluence_score": result.get("confluence_score"),
                "trade_plan": result.get("trade_plan"),
                "score_breakdown": result.get("score_breakdown"),
            }),
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


# ── Batch scan route is defined in routes/watchlist.py ──────────────────