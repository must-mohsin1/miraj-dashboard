"""Scan diff + changes timeline routes.

GET /api/v1/scan/{symbol}/diff
    Compare the last 2 scans for a symbol and return the diff.

GET /api/v1/scan/{symbol}/changes
    Return a timeline of all changes across all scans for a symbol,
    plus a score progression series for charting.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import Analysis, User
from backend.services import diff_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/scan", tags=["scan-diff"])

#: Analysis rows that carry the full normalized scan result and therefore
#: participate in field-level diffs.  Scheduled 4-hour scans persist the same
#: blob as manual scans (see ``build_persistable_result``), so the timeline
#: interleaves both.
_DIFFABLE_TYPES: tuple[str, ...] = ("scan", "scheduled_scan")


# ── Response models ────────────────────────────────────────────────────────


class ScanDiffEntry(BaseModel):
    """A single field-level change between two scans."""

    field: str = Field(..., description="Dotted path, e.g. 'qqe_signals.4h'")
    change: str = Field(..., description="Human-readable change description")
    severity: str = Field(..., description="'major' | 'minor' | 'info'")
    old_value: Any | None = None
    new_value: Any | None = None
    timestamp: str = Field(..., description="ISO-8601 of the newer scan")


class ScanDiffResponse(BaseModel):
    """Response for GET /api/v1/scan/{symbol}/diff."""

    symbol: str
    previous_scan_at: str
    latest_scan_at: str
    previous_score: Optional[float] = None
    latest_score: Optional[float] = None
    changes: list[ScanDiffEntry]
    summary: dict[str, int]


class ScorePoint(BaseModel):
    """One point on the score progression series."""

    timestamp: str
    confluence_score: Optional[float] = None
    overall_score: Optional[float] = None
    direction: Optional[str] = None
    trade_decision: Optional[bool] = None


class TimelineGroup(BaseModel):
    """One group of changes (per adjacent scan pair)."""

    scan_at: str
    score_before: Optional[float] = None
    score_after: Optional[float] = None
    changes: list[ScanDiffEntry]


class ScanChangesTimelineResponse(BaseModel):
    """Response for GET /api/v1/scan/{symbol}/changes."""

    symbol: str
    total_scans: int
    score_progression: list[ScorePoint]
    timeline: list[TimelineGroup]
    summary: dict[str, int]


# ── Helpers ────────────────────────────────────────────────────────────────


def _parse_result(raw: Optional[str]) -> dict[str, Any]:
    """Parse the ``result`` JSON column into a dict; ``{}`` on any failure."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _extract_score_point(a: Analysis) -> ScorePoint:
    """Build a ``ScorePoint`` from a single Analysis row."""
    data = _parse_result(a.result)
    conf = data.get("confluence_score")
    overall = data.get("overall_score") or a.score
    trade_plan = data.get("trade_plan") if isinstance(data.get("trade_plan"), dict) else {}
    flat = data.get("trade_plan_flat") if isinstance(data.get("trade_plan_flat"), dict) else {}
    direction = (flat.get("direction") or trade_plan.get("direction") if isinstance(trade_plan, dict) else None)
    decision = trade_plan.get("trade_decision") if isinstance(trade_plan, dict) else None
    return ScorePoint(
        timestamp=a.created_at.isoformat() if a.created_at else "",
        confluence_score=round(float(conf), 1) if conf is not None else None,
        overall_score=round(float(overall), 1) if overall is not None else None,
        direction=(str(direction).upper() if direction else None),
        trade_decision=bool(decision) if decision is not None else None,
    )


# ── GET /api/v1/scan/{symbol}/diff ──────────────────────────────────────────


@router.get(
    "/{symbol}/diff",
    response_model=ScanDiffResponse,
)
async def get_scan_diff(
    symbol: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Diff the two most recent scans for *symbol* owned by the current user.

    Returns 404 when fewer than 2 scans exist for the symbol.
    """
    sym = symbol.strip().upper()
    stmt = (
        select(Analysis)
        .where(
            Analysis.user_id == current_user.id,
            Analysis.pair == sym,
            Analysis.analysis_type.in_(_DIFFABLE_TYPES),
        )
        .order_by(Analysis.created_at.desc())
        .limit(2)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if len(rows) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Not enough scans for {sym} to compute a diff",
        )
    latest = rows[0]
    previous = rows[1]

    prev_result = _parse_result(previous.result)
    cur_result = _parse_result(latest.result)

    changes_list = diff_service.diff_scans(
        prev_result, cur_result,
        previous.created_at, latest.created_at,
    )

    prev_score = prev_result.get("confluence_score")
    cur_score = cur_result.get("confluence_score")

    return ScanDiffResponse(
        symbol=sym,
        previous_scan_at=previous.created_at.isoformat(),
        latest_scan_at=latest.created_at.isoformat(),
        previous_score=round(float(prev_score), 1) if prev_score is not None else None,
        latest_score=round(float(cur_score), 1) if cur_score is not None else None,
        changes=[ScanDiffEntry(**e) for e in changes_list],
        summary=diff_service.summarise(changes_list),
    )


# ── GET /api/v1/scan/{symbol}/changes ─────────────────────────────────────


@router.get(
    "/{symbol}/changes",
    response_model=ScanChangesTimelineResponse,
)
async def get_scan_changes(
    symbol: str,
    limit: int = Query(50, ge=1, le=200, description="Max scans to diff"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Return a full timeline of changes across all scans for *symbol*.

    Builds a score-progression series (one point per scan) plus a pairwise
    change timeline (one group per adjacent scan pair).

    Returns 404 when zero scans exist for the symbol.
    """
    sym = symbol.strip().upper()
    stmt = (
        select(Analysis)
        .where(
            Analysis.user_id == current_user.id,
            Analysis.pair == sym,
            Analysis.analysis_type.in_(_DIFFABLE_TYPES),
        )
        .order_by(Analysis.created_at.asc())  # oldest first
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scans found for {sym}",
        )

    # Score-progression series — one point per scan, chronological order.
    score_progression: list[ScorePoint] = [_extract_score_point(r) for r in rows]

    # Pairwise diff timeline — one group per adjacent scan pair.
    timeline: list[TimelineGroup] = []
    total_summary: dict[str, int] = {"major": 0, "minor": 0, "info": 0}

    for i in range(1, len(rows)):
        older = rows[i - 1]
        newer = rows[i]
        prev_result = _parse_result(older.result)
        cur_result = _parse_result(newer.result)
        entries = diff_service.diff_scans(
            prev_result, cur_result,
            older.created_at, newer.created_at,
        )
        for k, v in diff_service.summarise(entries).items():
            total_summary[k] = total_summary.get(k, 0) + v

        prev_score = prev_result.get("confluence_score")
        new_score = cur_result.get("confluence_score")
        timeline.append(TimelineGroup(
            scan_at=newer.created_at.isoformat(),
            score_before=round(float(prev_score), 1) if prev_score is not None else None,
            score_after=round(float(new_score), 1) if new_score is not None else None,
            changes=[ScanDiffEntry(**e) for e in entries],
        ))

    return ScanChangesTimelineResponse(
        symbol=sym,
        total_scans=len(rows),
        score_progression=score_progression,
        timeline=timeline,
        summary=total_summary,
    )
