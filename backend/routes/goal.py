"""Monthly profit goal routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import User
from backend.services.goal_service import (
    DEFAULT_EXCHANGE,
    close_stale_goals,
    snapshot_now,
    upsert_open_goal,
)

router = APIRouter(prefix="/api/v1/goal", tags=["goal"])


class GoalUpdateRequest(BaseModel):
    target_return_pct: float = Field(..., gt=0, le=500)
    redeem_pct: float = Field(0, ge=0, le=100)
    base_equity: Optional[float] = Field(None, gt=0)
    exchange: str = DEFAULT_EXCHANGE


@router.get("/now")
async def get_goal_now(
    exchange: str = Query(DEFAULT_EXCHANGE),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    normalized_exchange = exchange.lower()
    await close_stale_goals(session, int(current_user.id), normalized_exchange)
    return await snapshot_now(session, int(current_user.id), normalized_exchange)


@router.put("/now")
async def put_goal_now(
    body: GoalUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    normalized_exchange = body.exchange.lower()
    await close_stale_goals(session, int(current_user.id), normalized_exchange)
    try:
        await upsert_open_goal(
            session,
            int(current_user.id),
            normalized_exchange,
            target_return_pct=body.target_return_pct,
            redeem_pct=body.redeem_pct,
            base_equity=body.base_equity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    await session.commit()
    return await snapshot_now(session, int(current_user.id), normalized_exchange)
