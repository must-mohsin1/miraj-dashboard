"""Results history route — paginated scan results.

GET /api/v1/results
    Query parameters:
        symbol    (optional) Filter by trading pair, e.g. ``BTCUSDT``
        limit     (optional) Max rows per page (default 20, max 100)
        offset    (optional) Row offset for pagination
        from_date (optional) ISO datetime — inclusive lower bound
        to_date   (optional) ISO datetime — inclusive upper bound

    Responses
    --------
    200 — ``{items: [...], total: N, limit: N, offset: N}``
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import Analysis, ScanRun, User
from backend.schemas import AnalysisResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["results"])


# ── Pydantic response models (inline) ────────────────────────────────────
from pydantic import BaseModel  # noqa: E402


class PaginatedResults(BaseModel):
    items: list[AnalysisResponse]
    total: int
    limit: int
    offset: int

    model_config = {"json_schema_extra": {"example": {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }}}


# ── Route ────────────────────────────────────────────────────────────────


def _parse_json(value: Optional[str]) -> Optional[dict[str, Any]]:
    """Parse a JSON string column into a dict, returning None on failure."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


@router.get("/results", response_model=PaginatedResults)
async def get_results(
    symbol: Optional[str] = Query(None, description="Filter by trading pair (e.g. BTCUSDT)"),
    limit: int = Query(20, ge=1, le=100, description="Max rows per page"),
    offset: int = Query(0, ge=0, description="Row offset for pagination"),
    from_date: Optional[datetime] = Query(
        None, alias="from_date", description="Inclusive lower bound (ISO datetime)"
    ),
    to_date: Optional[datetime] = Query(
        None, alias="to_date", description="Inclusive upper bound (ISO datetime)"
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResults:
    """Return paginated scan results for the current user.

    Results are sorted by ``created_at`` descending (newest first).
    """
    # ── Build query ────────────────────────────────────────────────
    conditions = [Analysis.user_id == current_user.id]

    if symbol:
        conditions.append(Analysis.pair == symbol.strip().upper())

    if from_date is not None:
        conditions.append(Analysis.created_at >= from_date)

    if to_date is not None:
        conditions.append(Analysis.created_at <= to_date)

    # ── Count total matching rows ──────────────────────────────────
    count_q = select(func.count()).select_from(Analysis).where(*conditions)
    total_result = await session.execute(count_q)
    total: int = total_result.scalar_one()

    # ── Fetch page ─────────────────────────────────────────────────
    query = (
        select(Analysis)
        .where(*conditions)
        .order_by(Analysis.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(query)
    analyses = result.scalars().all()

    items = [
        AnalysisResponse.model_validate({
            "id": a.id,
            "user_id": a.user_id,
            "pair": a.pair,
            "analysis_type": a.analysis_type,
            "parameters": _parse_json(a.parameters),
            "result": _parse_json(a.result),
            "created_at": a.created_at,
        })
        for a in analyses
    ]

    return PaginatedResults(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
