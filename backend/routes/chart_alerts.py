"""Authenticated preferences and deduplicated history for chart alerts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import ChartAlertEvent, ChartAlertPreference, PriceAlert, User

router = APIRouter(prefix="/api/v1/chart-alerts", tags=["chart_alerts"])
Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]


class PreferencePayload(BaseModel):
    enabled: bool


class PreferenceResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    enabled: bool
    updated_at: datetime | None = None


class SetupPayload(BaseModel):
    direction: Literal["LONG", "SHORT"]
    entry: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    targets: list[float] = Field(default_factory=list, max_length=5)
    enabled: bool = True


class SetupResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    enabled: bool
    server_alert_count: int


class EventPayload(BaseModel):
    event_key: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=40)
    timeframe: Timeframe
    event_type: str = Field(min_length=1, max_length=32)
    direction: str | None = Field(default=None, max_length=10)
    price: float = Field(gt=0)
    candle_time: int = Field(gt=0)


class EventResponse(BaseModel):
    created: bool
    event_key: str


class HistoryItem(BaseModel):
    event_key: str
    symbol: str
    timeframe: str
    event_type: str
    direction: str | None
    price: float
    candle_time: int
    created_at: datetime


class HistoryResponse(BaseModel):
    events: list[HistoryItem]
    total: int


async def _get_preference(
    session: AsyncSession, user_id: int, symbol: str, timeframe: str
) -> ChartAlertPreference | None:
    result = await session.execute(
        select(ChartAlertPreference).where(
            ChartAlertPreference.user_id == user_id,
            ChartAlertPreference.symbol == symbol,
            ChartAlertPreference.timeframe == timeframe,
        )
    )
    return result.scalar_one_or_none()


@router.get("/preferences", response_model=PreferenceResponse)
async def get_preference(
    symbol: str = Query(..., min_length=1),
    timeframe: Timeframe = Query("1d"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PreferenceResponse:
    symbol_norm = symbol.strip().upper()
    row = await _get_preference(session, current_user.id, symbol_norm, timeframe)
    return PreferenceResponse(
        symbol=symbol_norm,
        timeframe=timeframe,
        enabled=bool(row.enabled) if row else False,
        updated_at=row.updated_at if row else None,
    )


@router.put("/preferences", response_model=PreferenceResponse)
async def set_preference(
    payload: PreferencePayload,
    symbol: str = Query(..., min_length=1),
    timeframe: Timeframe = Query("1d"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PreferenceResponse:
    symbol_norm = symbol.strip().upper()
    row = await _get_preference(session, current_user.id, symbol_norm, timeframe)
    if row is None:
        row = ChartAlertPreference(
            user_id=current_user.id,
            symbol=symbol_norm,
            timeframe=timeframe,
            enabled=payload.enabled,
        )
        session.add(row)
    else:
        row.enabled = payload.enabled
    await session.flush()
    return PreferenceResponse(
        symbol=symbol_norm,
        timeframe=timeframe,
        enabled=bool(row.enabled),
        updated_at=row.updated_at,
    )


@router.put("/setup", response_model=SetupResponse)
async def sync_server_setup(
    payload: SetupPayload,
    symbol: str = Query(..., min_length=1),
    timeframe: Timeframe = Query("1d"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SetupResponse:
    """Synchronize chart levels into the existing server-side price-alert worker."""
    symbol_norm = symbol.strip().upper()
    prefix = f"chart:{symbol_norm}:{timeframe}:"
    await session.execute(
        sa_delete(PriceAlert).where(
            PriceAlert.user_id == current_user.id,
            PriceAlert.symbol == symbol_norm,
            PriceAlert.message.like(f"{prefix}%"),
        )
    )
    count = 0
    if payload.enabled:
        crossing = "below" if payload.direction == "SHORT" else "above"
        inverse = "above" if payload.direction == "SHORT" else "below"
        levels: list[tuple[str, float | None, str, str]] = [
            ("trigger", payload.entry, crossing, "price"),
            ("invalidation", payload.stop_loss, inverse, "stop"),
        ]
        levels.extend((f"tp{index + 1}", price, crossing, "target") for index, price in enumerate(payload.targets))
        for label, price, direction, alert_type in levels:
            if price is None:
                continue
            session.add(
                PriceAlert(
                    user_id=current_user.id,
                    symbol=symbol_norm,
                    alert_type=alert_type,
                    direction=direction,
                    price_level=price,
                    message=f"{prefix}{payload.direction}:{label}",
                    status="active",
                )
            )
            count += 1
    preference = await _get_preference(session, current_user.id, symbol_norm, timeframe)
    if preference is None:
        session.add(ChartAlertPreference(user_id=current_user.id, symbol=symbol_norm, timeframe=timeframe, enabled=payload.enabled))
    else:
        preference.enabled = payload.enabled
    await session.flush()
    return SetupResponse(symbol=symbol_norm, timeframe=timeframe, enabled=payload.enabled, server_alert_count=count)


@router.post("/events", response_model=EventResponse)
async def record_event(
    payload: EventPayload,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EventResponse:
    result = await session.execute(
        select(ChartAlertEvent).where(
            ChartAlertEvent.user_id == current_user.id,
            ChartAlertEvent.event_key == payload.event_key,
        )
    )
    if result.scalar_one_or_none() is not None:
        return EventResponse(created=False, event_key=payload.event_key)
    row = ChartAlertEvent(
        user_id=current_user.id,
        event_key=payload.event_key,
        symbol=payload.symbol.strip().upper(),
        timeframe=payload.timeframe,
        event_type=payload.event_type,
        direction=payload.direction,
        price=payload.price,
        candle_time=payload.candle_time,
    )
    session.add(row)
    await session.flush()
    return EventResponse(created=True, event_key=payload.event_key)


@router.get("/history", response_model=HistoryResponse)
async def list_history(
    symbol: str | None = Query(None),
    timeframe: Timeframe | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HistoryResponse:
    query = select(ChartAlertEvent).where(ChartAlertEvent.user_id == current_user.id)
    if symbol:
        query = query.where(ChartAlertEvent.symbol == symbol.strip().upper())
    if timeframe:
        query = query.where(ChartAlertEvent.timeframe == timeframe)
    query = query.order_by(ChartAlertEvent.created_at.desc()).limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()
    return HistoryResponse(
        events=[
            HistoryItem(
                event_key=row.event_key,
                symbol=row.symbol,
                timeframe=row.timeframe,
                event_type=row.event_type,
                direction=row.direction,
                price=row.price,
                candle_time=row.candle_time,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=len(rows),
    )
