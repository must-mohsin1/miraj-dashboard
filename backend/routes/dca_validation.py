"""Read-only DCA validation API routes.

This module intentionally is not registered from ``backend.main`` yet; the
integration card owns shared route wiring. Tests import and mount ``router``
directly.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import Analysis, PortfolioPosition, User

try:  # Upstream service card; available after integration.
    from backend.services.dca_validation_reconstruction import reconstruct_scan_history
except ImportError:  # pragma: no cover - exercised only before integration lands.
    reconstruct_scan_history = None  # type: ignore[assignment]

try:  # Upstream service card; available after integration.
    from backend.services.dca_validation_metrics import compute_dca_validation_metrics
except ImportError:  # pragma: no cover - exercised only before integration lands.
    compute_dca_validation_metrics = None  # type: ignore[assignment]

try:  # Upstream service card; available after integration.
    from backend.services.dca_shadow_service import list_shadow_history
except ImportError:  # pragma: no cover - exercised only before integration lands.
    list_shadow_history = None  # type: ignore[assignment]


router = APIRouter(prefix="/api/v1/dca-validation", tags=["dca-validation"])

REQUEST_BUDGET_MS = 2500
DISCLAIMER = (
    "These are reconstructed and shadow-mode results, not realized trading "
    "performance or financial advice."
)
_METHOD_DESCRIPTION = "scan-history reconstruction; not candle-level historical replay"

# Process-local cache for non-blocking retry/refresh behavior. It is deliberately
# keyed by user_id so one user's last completed validation cannot bleed into
# another user's timeout response.
_LAST_COMPLETED: Dict[Tuple[Any, ...], Dict[str, Any]] = {}


class ValidationRequestEcho(BaseModel):
    exchange: str
    symbol: Optional[str] = None
    outcome: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    split_ratio: float
    limit: int
    timeout_ms: int


class ValidationErrorItem(BaseModel):
    field: str
    message: str


class DcaValidationResponse(BaseModel):
    state: str = Field(
        description="metrics_available, insufficient_history, reconstructing, or validation_error"
    )
    exchange: str
    request: ValidationRequestEcho
    reconstruction: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    shadow_history: List[Dict[str, Any]] = []
    validation_errors: List[ValidationErrorItem] = []
    last_completed: Optional[Dict[str, Any]] = None
    disclaimer: str = DISCLAIMER


def _validate_split_ratio(split_ratio: float) -> None:
    if split_ratio <= 0 or split_ratio >= 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="split_ratio must be greater than 0 and less than 1",
        )


def _normalise_exchange(exchange: str) -> str:
    exchange_slug = exchange.strip().lower()
    if not exchange_slug:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="exchange path parameter is required",
        )
    return exchange_slug


def _normalise_symbol(symbol: Optional[str]) -> Optional[str]:
    if symbol is None:
        return None
    cleaned = symbol.strip().upper()
    return cleaned or None


def _cache_key(
    user_id: int,
    exchange: str,
    symbol: Optional[str],
    outcome: Optional[str],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    split_ratio: float,
    limit: int,
) -> Tuple[Any, ...]:
    return (
        user_id,
        exchange,
        symbol,
        outcome,
        start_date.isoformat() if start_date else None,
        end_date.isoformat() if end_date else None,
        split_ratio,
        limit,
    )


def _response_state(reconstruction: Dict[str, Any], metrics: Optional[Dict[str, Any]]) -> str:
    symbols = reconstruction.get("symbols") or []
    if metrics and (metrics.get("symbols") or metrics.get("portfolio")):
        return "metrics_available"
    if any(item.get("status") in {"metrics_available", "eligible"} for item in symbols):
        return "metrics_available"
    if any(item.get("status") == "insufficient_history" for item in symbols) or symbols == []:
        return "insufficient_history"
    return "reconstructing"


def _serialise_dt(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _parse_json_blob(blob: Optional[str]) -> Dict[str, Any]:
    if not blob:
        return {}
    try:
        parsed = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _analysis_matches_exchange(analysis: Analysis, exchange: str) -> bool:
    """Best-effort exchange filter for legacy Analysis rows.

    Older Analysis rows do not have a first-class exchange column. When a row
    stores exchange in parameters/result, require it to match the path. When no
    exchange metadata exists, keep the row but it remains scoped to user_id by
    the caller's query.
    """
    params = _parse_json_blob(analysis.parameters)
    result = _parse_json_blob(analysis.result)
    recorded = params.get("exchange") or result.get("exchange")
    return recorded is None or str(recorded).lower() == exchange


async def _fallback_reconstruct_scan_history(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Minimal user-scoped reconstruction summary used until service integration.

    Every database query includes ``user_id``. Portfolio rows are additionally
    scoped to the requested exchange; Analysis rows are scoped by user and then
    best-effort filtered by exchange metadata because the model has no exchange
    column.
    """
    analysis_query = select(Analysis).where(Analysis.user_id == user_id)
    if symbol:
        analysis_query = analysis_query.where(Analysis.pair == symbol)
    if start_date:
        analysis_query = analysis_query.where(Analysis.created_at >= start_date)
    if end_date:
        analysis_query = analysis_query.where(Analysis.created_at <= end_date)
    analysis_query = analysis_query.order_by(Analysis.pair.asc(), Analysis.created_at.asc())
    analysis_rows = list((await session.execute(analysis_query)).scalars().all())
    analysis_rows = [row for row in analysis_rows if _analysis_matches_exchange(row, exchange)]

    position_query = select(PortfolioPosition.symbol).where(
        PortfolioPosition.user_id == user_id,
        PortfolioPosition.exchange == exchange,
    )
    if symbol:
        position_query = position_query.where(PortfolioPosition.symbol == symbol)
    position_symbols = set((await session.execute(position_query)).scalars().all())

    by_symbol: Dict[str, List[Analysis]] = {}
    for row in analysis_rows:
        by_symbol.setdefault(row.pair, []).append(row)
    for pos_symbol in position_symbols:
        by_symbol.setdefault(pos_symbol, [])

    symbols: List[Dict[str, Any]] = []
    for item_symbol, rows in sorted(by_symbol.items()):
        scan_count = len(rows)
        first_scan = rows[0].created_at if rows else None
        last_scan = rows[-1].created_at if rows else None
        max_gap = None
        if scan_count >= 2:
            gaps = [
                (rows[index].created_at - rows[index - 1].created_at).total_seconds()
                for index in range(1, scan_count)
            ]
            max_gap = max(gaps) if gaps else None
        events = []
        skipped_scans = []
        for row in rows[-50:]:
            result = _parse_json_blob(row.result)
            recommendation = (
                result.get("dca", {}).get("recommendation")
                or result.get("dca_recommendation")
                or result.get("recommendation")
            )
            if recommendation:
                events.append(
                    {
                        "timestamp": row.created_at.isoformat(),
                        "symbol": item_symbol,
                        "recommendation": str(recommendation),
                        "confidence": result.get("confidence"),
                        "reason": result.get("reason"),
                        "participates_in_metrics": scan_count >= 2,
                    }
                )
            else:
                skipped_scans.append(
                    {
                        "timestamp": row.created_at.isoformat(),
                        "symbol": item_symbol,
                        "reason": "missing_trade_plan",
                    }
                )
        symbols.append(
            {
                "symbol": item_symbol,
                "status": "metrics_available" if scan_count >= 2 else "insufficient_history",
                "required_minimum_scans": 2,
                "scan_count": scan_count,
                "first_scan_at": _serialise_dt(first_scan),
                "last_scan_at": _serialise_dt(last_scan),
                "max_scan_gap_seconds": max_gap,
                "events": events,
                "skipped_scans": skipped_scans,
            }
        )

    return {
        "exchange": exchange,
        "method": "scan-to-scan",
        "method_description": _METHOD_DESCRIPTION,
        "fill_assumptions": {
            "long_rsi_entries": [30, 24, 16],
            "short_rsi_entries": [80, 92, 95],
            "allocation_percentages": [20, 20, 60],
            "slippage_percent": 0.05,
            "fee_percent": 0.04,
        },
        "symbols": symbols,
    }


def _fallback_compute_metrics(
    reconstruction: Dict[str, Any], *, split_ratio: float
) -> Optional[Dict[str, Any]]:
    eligible = [
        item for item in reconstruction.get("symbols", [])
        if item.get("status") == "metrics_available"
    ]
    if not eligible:
        return None
    return {
        "exchange": reconstruction.get("exchange"),
        "split_ratio": split_ratio,
        "symbols": [
            {
                "symbol": item["symbol"],
                "status": "metrics_available",
                "metrics": {
                    "win_rate": {"value": None, "reason": "metrics service unavailable"},
                    "profit_factor": {"value": None, "reason": "metrics service unavailable"},
                },
            }
            for item in eligible
        ],
        "portfolio": {"metrics": {}},
    }


async def _fallback_list_shadow_history(**_: Any) -> List[Dict[str, Any]]:
    return []


async def _build_validation_payload(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: Optional[str],
    outcome: Optional[str],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    split_ratio: float,
    limit: int,
) -> Dict[str, Any]:
    reconstructor = reconstruct_scan_history or _fallback_reconstruct_scan_history
    metrics_fn = compute_dca_validation_metrics or _fallback_compute_metrics
    shadow_fn = list_shadow_history or _fallback_list_shadow_history

    reconstruction = await reconstructor(
        session,
        user_id,
        exchange,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
    )
    metrics = metrics_fn(reconstruction, split_ratio=split_ratio)
    shadow_history = await _maybe_await(
        shadow_fn(
            session=session,
            user_id=user_id,
            exchange=exchange,
            symbol=symbol,
            outcome=outcome,
            start=start_date,
            end=end_date,
            limit=limit,
        )
    )
    state = _response_state(reconstruction, metrics)
    if state == "insufficient_history":
        metrics = None
    return {
        "state": state,
        "reconstruction": reconstruction,
        "metrics": metrics,
        "shadow_history": shadow_history or [],
    }


@router.get(
    "/{exchange}",
    response_model=DcaValidationResponse,
    responses={422: {"description": "Invalid validation request"}},
)
async def get_dca_validation(
    exchange: str,
    symbol: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    split_ratio: float = Query(default=0.7),
    limit: int = Query(default=50, ge=1, le=200),
    timeout_ms: int = Query(default=REQUEST_BUDGET_MS, ge=1, le=30000),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DcaValidationResponse:
    """Return read-only DCA validation for the authenticated user's data."""
    exchange_slug = _normalise_exchange(exchange)
    symbol_slug = _normalise_symbol(symbol)
    _validate_split_ratio(split_ratio)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date must be before or equal to end_date",
        )

    request_echo = ValidationRequestEcho(
        exchange=exchange_slug,
        symbol=symbol_slug,
        outcome=outcome,
        start_date=start_date,
        end_date=end_date,
        split_ratio=split_ratio,
        limit=limit,
        timeout_ms=timeout_ms,
    )
    key = _cache_key(
        current_user.id,
        exchange_slug,
        symbol_slug,
        outcome,
        start_date,
        end_date,
        split_ratio,
        limit,
    )

    try:
        payload = await asyncio.wait_for(
            _build_validation_payload(
                session,
                current_user.id,
                exchange_slug,
                symbol_slug,
                outcome,
                start_date,
                end_date,
                split_ratio,
                limit,
            ),
            timeout=timeout_ms / 1000,
        )
    except asyncio.TimeoutError:
        cached = _LAST_COMPLETED.get(key)
        last_completed = None
        if cached:
            last_completed = {
                "completed_at": cached["completed_at"],
                "state": cached["payload"]["state"],
            }
        return DcaValidationResponse(
            state="reconstructing",
            exchange=exchange_slug,
            request=request_echo,
            reconstruction=(cached or {}).get("payload", {}).get("reconstruction"),
            metrics=(cached or {}).get("payload", {}).get("metrics"),
            shadow_history=(cached or {}).get("payload", {}).get("shadow_history", []),
            last_completed=last_completed,
            validation_errors=[],
        )

    _LAST_COMPLETED[key] = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    return DcaValidationResponse(
        state=payload["state"],
        exchange=exchange_slug,
        request=request_echo,
        reconstruction=payload["reconstruction"],
        metrics=payload["metrics"],
        shadow_history=payload["shadow_history"],
        validation_errors=[],
        last_completed=None,
    )
