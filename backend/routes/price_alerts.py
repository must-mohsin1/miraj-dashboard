"""Price alert routes — CRUD for user price alerts.

Endpoints
---------
POST   /api/v1/alerts/price              — create a price alert
GET    /api/v1/alerts/price              — list price alerts (optional ``?status=active|triggered|cancelled``)
GET    /api/v1/alerts/price/{id}         — get a single price alert
PUT    /api/v1/alerts/price/{id}         — update/cancel a price alert
DELETE /api/v1/alerts/price/{id}         — delete a price alert
POST   /api/v1/alerts/price/test         — send a test Telegram alert
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import PriceAlert, User
from backend.services.price_alert_service import (
    cancel_price_alert,
    create_price_alert,
    delete_price_alert,
    get_price_alert,
    list_price_alerts,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alerts/price", tags=["price_alerts"])


# ── Pydantic models ────────────────────────────────────────────────────────


class PriceAlertCreateRequest(BaseModel):
    """Request body for creating a new price alert."""

    symbol: str = Field(..., min_length=1, max_length=20, description="Trading symbol (e.g. BTC-USD)")
    price_level: float = Field(..., gt=0, description="Trigger price level")
    direction: str = Field(..., pattern="^(above|below)$", description="Trigger direction: 'above' or 'below'")
    alert_type: str = Field("price", pattern="^(price|target|stop)$")
    message: Optional[str] = Field(None, max_length=500, description="Optional custom message")


class PriceAlertUpdateRequest(BaseModel):
    """Request body for updating a price alert (currently only supports cancellation)."""

    status: str = Field(..., pattern="^(cancelled)$", description="New status (cancelled)")


class PriceAlertResponse(BaseModel):
    """Response body for a single price alert."""

    id: int
    user_id: int
    symbol: str
    alert_type: str
    direction: str
    price_level: float
    current_price: Optional[float] = None
    message: Optional[str] = None
    status: str
    triggered_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PriceAlertListResponse(BaseModel):
    """Wrapper for GET /api/v1/alerts/price."""

    total: int
    alerts: list[PriceAlertResponse]


# ── Routes ─────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=PriceAlertResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert(
    body: PriceAlertCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PriceAlertResponse:
    """Create a new price alert.

    When the price of *symbol* crosses *price_level* in the specified
    *direction*, a notification is sent via the user's enabled alert channels.
    """
    alert = await create_price_alert(
        session=session,
        user_id=current_user.id,
        symbol=body.symbol,
        price_level=body.price_level,
        direction=body.direction,
        alert_type=body.alert_type,
        message=body.message,
    )
    return PriceAlertResponse(
        id=alert.id,
        user_id=alert.user_id,
        symbol=alert.symbol,
        alert_type=alert.alert_type,
        direction=alert.direction,
        price_level=alert.price_level,
        current_price=alert.current_price,
        message=alert.message,
        status=alert.status,
        triggered_at=alert.triggered_at,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


@router.get("", response_model=PriceAlertListResponse)
async def list_alerts(
    status_filter: Optional[str] = Query(
        None, alias="status", pattern="^(active|triggered|cancelled)?$"
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PriceAlertListResponse:
    """List price alerts for the current user.

    Optionally filter by status: ``active``, ``triggered``, or ``cancelled``.
    Results are ordered by creation date (newest first).
    """
    alerts = await list_price_alerts(session, current_user.id, status=status_filter)
    return PriceAlertListResponse(
        total=len(alerts),
        alerts=[
            PriceAlertResponse(
                id=a.id,
                user_id=a.user_id,
                symbol=a.symbol,
                alert_type=a.alert_type,
                direction=a.direction,
                price_level=a.price_level,
                current_price=a.current_price,
                message=a.message,
                status=a.status,
                triggered_at=a.triggered_at,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in alerts
        ],
    )


class TestAlertResponse(BaseModel):
    """Response body for POST /api/v1/alerts/price/test."""
    ok: bool
    error: Optional[str] = None


# IMPORTANT: This route MUST be placed before ``/{alert_id}`` so that
# FastAPI does not interpret ``test`` as a path parameter.
@router.post("/test", response_model=TestAlertResponse)
async def test_telegram_alert(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TestAlertResponse:
    """Send a test Telegram alert to the user's configured channel.

    Finds the user's first enabled Telegram ``AlertChannel``, sends a
    test message, and returns ``{ok: true}`` on success or
    ``{ok: false, error: "..."}`` on failure.
    """
    from backend.alerts.telegram import send_alert
    from backend.models import AlertChannel
    from sqlalchemy import select
    import json

    result = await session.execute(
        select(AlertChannel).where(
            AlertChannel.user_id == current_user.id,
            AlertChannel.channel_type == "telegram",
            AlertChannel.enabled == 1,
        )
    )
    channel = result.scalar_one_or_none()

    if not channel:
        return TestAlertResponse(
            ok=False,
            error="No enabled Telegram channel found. Add one in Settings → Alerts.",
        )

    try:
        config = json.loads(channel.config) if channel.config else {}
    except (json.JSONDecodeError, TypeError):
        config = {}

    chat_id = config.get("chat_id")
    if not chat_id:
        return TestAlertResponse(
            ok=False,
            error="Telegram channel is missing a chat_id in its config.",
        )

    message = (
        "🔔 *Test Alert from Miraj Dashboard*\n\n"
        "✅ Your Telegram alert channel is working!\n\n"
        "Active alerts will be sent here when price thresholds are hit.\n"
        f"Connected as: *{current_user.username}*"
    )

    success = await send_alert(str(chat_id), message)
    return TestAlertResponse(
        ok=success,
        error=None if success else "Telegram send failed. Check bot token and chat ID.",
    )


@router.get("/{alert_id}", response_model=PriceAlertResponse)
async def get_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PriceAlertResponse:
    """Get a single price alert by id."""
    alert = await get_price_alert(session, alert_id, current_user.id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Price alert not found",
        )
    return PriceAlertResponse(
        id=alert.id,
        user_id=alert.user_id,
        symbol=alert.symbol,
        alert_type=alert.alert_type,
        direction=alert.direction,
        price_level=alert.price_level,
        current_price=alert.current_price,
        message=alert.message,
        status=alert.status,
        triggered_at=alert.triggered_at,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


@router.put("/{alert_id}", response_model=PriceAlertResponse)
async def update_alert(
    alert_id: int,
    body: PriceAlertUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PriceAlertResponse:
    """Update a price alert (currently only supports cancellation)."""
    if body.status == "cancelled":
        alert = await cancel_price_alert(session, alert_id, current_user.id)
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Price alert not found",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported status: {body.status}",
        )

    return PriceAlertResponse(
        id=alert.id,
        user_id=alert.user_id,
        symbol=alert.symbol,
        alert_type=alert.alert_type,
        direction=alert.direction,
        price_level=alert.price_level,
        current_price=alert.current_price,
        message=alert.message,
        status=alert.status,
        triggered_at=alert.triggered_at,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a price alert permanently."""
    deleted = await delete_price_alert(session, alert_id, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Price alert not found",
        )
