"""History route — paginated list, delete, and export of past analyses.

GET    /api/v1/history          — paginated list with filters
DELETE /api/v1/history/{id}     — delete a single analysis row
GET    /api/v1/history/export   — bulk markdown export for selected ids
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import Analysis, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/history", tags=["history"])


# ── Response models ─────────────────────────────────────────────────────────


class HistoryRow(BaseModel):
    """One row in the paginated history table."""

    id: int
    symbol: str  # maps to Analysis.pair
    analysis_type: str
    score: Optional[float] = None
    direction: Optional[str] = None
    alert_sent: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class HistoryResponse(BaseModel):
    """Paginated wrapper."""

    rows: list[HistoryRow]
    total: int
    page: int
    per_page: int
    pages: int


class DeleteResponse(BaseModel):
    deleted: bool
    deleted_id: int


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_result(result_str: Optional[str]) -> tuple[Optional[float], Optional[str], bool]:
    """Extract score, direction, and alert_sent from the JSON result blob."""
    if not result_str:
        return None, None, False
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return None, None, False

    # Try top-level overall_score first, then confluence_score
    score: Optional[float] = data.get("overall_score") or data.get("confluence_score")

    # Direction from trade_plan
    trade_plan = data.get("trade_plan", {}) or {}
    direction: Optional[str] = None
    raw_dir = trade_plan.get("direction")
    if isinstance(raw_dir, str) and raw_dir.strip():
        direction = raw_dir.strip().upper()

    # Alert sent = trade_decision is truthy
    trade_decision = trade_plan.get("trade_decision")
    alert_sent = bool(trade_decision) if trade_decision is not None else False

    return score, direction, alert_sent


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("", response_model=HistoryResponse)
async def list_history(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    symbol: Optional[str] = Query(None, description="Filter by trading pair"),
    from_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    min_score: Optional[float] = Query(None, ge=0, le=100, description="Minimum confluence score"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Return a paginated, filtered list of analyses for the current user."""
    # Base query — only current user's analyses
    base = select(Analysis).where(Analysis.user_id == current_user.id)

    # ── Filters ──────────────────────────────────────────────────
    if symbol:
        base = base.where(Analysis.pair == symbol.strip().upper())
    if from_date:
        from_dt = datetime(from_date.year, from_date.month, from_date.day)
        base = base.where(Analysis.created_at >= from_dt)
    if to_date:
        to_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59)
        base = base.where(Analysis.created_at <= to_dt)
    if min_score is not None:
        base = base.where(Analysis.score >= min_score)

    # Count total matching rows (with all filters applied)
    count_q = select(func.count()).select_from(base.subquery())
    total_result = await session.execute(count_q)
    total: int = total_result.scalar_one()

    # ── Pagination ────────────────────────────────────────────────
    pages = max(1, (total + per_page - 1) // per_page) if total else 1
    offset = (page - 1) * per_page

    rows_q = base.order_by(Analysis.created_at.desc()).offset(offset).limit(per_page)
    rows_result = await session.execute(rows_q)
    analyses = rows_result.scalars().all()

    # ── Build response rows ───────────────────────────────────────
    rows: list[HistoryRow] = []
    for a in analyses:
        score, direction, alert_sent = _parse_result(a.result)
        rows.append(
            HistoryRow(
                id=a.id,
                symbol=a.pair,
                analysis_type=a.analysis_type,
                score=round(score, 1) if score is not None else None,
                direction=direction,
                alert_sent=alert_sent,
                created_at=a.created_at,
            )
        )

    return HistoryResponse(
        rows=rows,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.delete("/{analysis_id}", response_model=DeleteResponse)
async def delete_analysis(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Delete a single analysis by id (must belong to the current user)."""
    stmt = (
        sa_delete(Analysis)
        .where(Analysis.id == analysis_id, Analysis.user_id == current_user.id)
    )
    result = await session.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found or access denied",
        )
    return DeleteResponse(deleted=True, deleted_id=analysis_id)


@router.get("/export")
async def export_history(
    ids: str = Query(..., description="Comma-separated analysis ids to export"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Return a markdown report for the selected analysis ids."""
    id_list = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        raise HTTPException(status_code=400, detail="No valid ids provided")

    stmt = (
        select(Analysis)
        .where(
            Analysis.id.in_(id_list),
            Analysis.user_id == current_user.id,
        )
        .order_by(Analysis.created_at.desc())
    )
    result = await session.execute(stmt)
    analyses = result.scalars().all()

    if not analyses:
        raise HTTPException(status_code=404, detail="No matching analyses found")

    lines = ["# Crypto Analysis Report", "", f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", ""]
    for a in analyses:
        score, direction, alert_sent = _parse_result(a.result)
        lines.append("---")
        lines.append(f"## {a.pair} — {a.created_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append(f"- **Symbol:** {a.pair}")
        lines.append(f"- **Type:** {a.analysis_type}")
        lines.append(f"- **Score:** {score}/100" if score is not None else "- **Score:** —")
        lines.append(f"- **Direction:** {direction}" if direction else "- **Direction:** —")
        lines.append(f"- **Alert Sent:** {'Yes' if alert_sent else 'No'}")
        lines.append("")

        # Try to include trade plan details
        if a.result:
            try:
                data = json.loads(a.result)
                tp = data.get("trade_plan", {}) or {}
                if tp:
                    lines.append("### Trade Plan")
                    lines.append("")
                    for k, v in tp.items():
                        if isinstance(v, bool):
                            lines.append(f"- **{k.replace('_', ' ').title()}:** {'Yes' if v else 'No'}")
                        elif v is not None:
                            if isinstance(v, float):
                                lines.append(f"- **{k.replace('_', ' ').title()}:** {v:.2f}")
                            else:
                                lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
                    lines.append("")
            except (json.JSONDecodeError, TypeError):
                pass

    return Response(content="\n".join(lines), media_type="text/markdown")
