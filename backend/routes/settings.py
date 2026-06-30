"""Settings routes — CRUD for user pair settings and alert channels.

Endpoints
---------
GET    /api/v1/settings/pairs           — list all pair settings for the current user
PUT    /api/v1/settings/pairs/{pair}    — update pair settings (alert_threshold, alert_enabled, etc.)
GET    /api/v1/settings/channels        — list all alert channels for the current user
POST   /api/v1/settings/channels        — create a new alert channel (Telegram / Discord)
PUT    /api/v1/settings/channels/{id}   — update an alert channel config
DELETE /api/v1/settings/channels/{id}   — delete an alert channel
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import AlertChannel, PairSetting, User
from backend.schemas import PairSettingsResponse, PairSettingsUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ── Helper: parse settings JSON ────────────────────────────────────────────


def _parse_settings_json(raw: str | None) -> dict[str, Any]:
    """Safely parse a JSON settings column, returning a dict."""
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Pydantic models for alert channel CRUD ─────────────────────────────────


class AlertChannelCreateRequest(BaseModel):
    """Request body for creating a new alert channel."""

    channel_type: str = Field(..., pattern="^(telegram|discord|email)$")
    config: dict[str, Any]
    enabled: bool = True


class AlertChannelUpdateRequest(BaseModel):
    """Request body for updating an existing alert channel."""

    config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None


class AlertChannelResponse(BaseModel):
    """Response body for a single alert channel."""

    id: int
    user_id: int
    channel_type: str
    config: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertChannelListResponse(BaseModel):
    """Wrapper for GET /api/v1/settings/channels."""

    total: int
    channels: list[AlertChannelResponse]


# ── Pair Settings ──────────────────────────────────────────────────────────


@router.get("/pairs", response_model=list[PairSettingsResponse])
async def list_pair_settings(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[PairSettingsResponse]:
    """List all pair settings for the current user."""
    result = await session.execute(
        select(PairSetting).where(PairSetting.user_id == current_user.id)
    )
    rows = result.scalars().all()
    return [
        PairSettingsResponse(
            id=row.id,
            user_id=row.user_id,
            pair=row.pair,
            settings=_parse_settings_json(row.settings),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.put("/pairs/{pair}", response_model=PairSettingsResponse)
async def update_pair_settings(
    pair: str,
    body: PairSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PairSettingsResponse:
    """Create or update settings for a pair (upsert by (user_id, pair)).

    *pair* in the path can be a normalised symbol (e.g. ``BTCUSDT``).
    The request body provides the full settings dict (``alert_threshold``,
    ``alert_enabled``, etc.).

    Returns 200 on create or update.
    """
    normalised = pair.strip().upper()
    if not normalised:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Pair symbol must not be empty",
        )

    # Check for existing row
    result = await session.execute(
        select(PairSetting).where(
            PairSetting.user_id == current_user.id,
            PairSetting.pair == normalised,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.settings = json.dumps(body.settings) if body.settings else None
        existing.updated_at = datetime.utcnow()
        row = existing
    else:
        row = PairSetting(
            user_id=current_user.id,
            pair=normalised,
            settings=json.dumps(body.settings) if body.settings else None,
        )
        session.add(row)

    await session.commit()
    await session.refresh(row)

    return PairSettingsResponse(
        id=row.id,
        user_id=row.user_id,
        pair=row.pair,
        settings=_parse_settings_json(row.settings),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ── Alert Channels ─────────────────────────────────────────────────────────


@router.get("/channels", response_model=AlertChannelListResponse)
async def list_alert_channels(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AlertChannelListResponse:
    """List all alert channels for the current user."""
    result = await session.execute(
        select(AlertChannel).where(AlertChannel.user_id == current_user.id)
    )
    rows = result.scalars().all()
    return AlertChannelListResponse(
        total=len(rows),
        channels=[
            AlertChannelResponse(
                id=ch.id,
                user_id=ch.user_id,
                channel_type=ch.channel_type,
                config=_parse_settings_json(ch.config),
                enabled=bool(ch.enabled),
                created_at=ch.created_at,
                updated_at=ch.updated_at,
            )
            for ch in rows
        ],
    )


@router.post(
    "/channels",
    response_model=AlertChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert_channel(
    body: AlertChannelCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AlertChannelResponse:
    """Create a new alert channel (Telegram or Discord)."""
    channel = AlertChannel(
        user_id=current_user.id,
        channel_type=body.channel_type,
        config=json.dumps(body.config),
        enabled=1 if body.enabled else 0,
    )
    session.add(channel)
    await session.commit()
    await session.refresh(channel)

    return AlertChannelResponse(
        id=channel.id,
        user_id=channel.user_id,
        channel_type=channel.channel_type,
        config=_parse_settings_json(channel.config),
        enabled=bool(channel.enabled),
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


@router.put("/channels/{channel_id}", response_model=AlertChannelResponse)
async def update_alert_channel(
    channel_id: int,
    body: AlertChannelUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AlertChannelResponse:
    """Update an existing alert channel's config or enabled status."""
    result = await session.execute(
        select(AlertChannel).where(
            AlertChannel.id == channel_id,
            AlertChannel.user_id == current_user.id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert channel not found",
        )

    if body.config is not None:
        channel.config = json.dumps(body.config)
    if body.enabled is not None:
        channel.enabled = 1 if body.enabled else 0
    channel.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(channel)

    return AlertChannelResponse(
        id=channel.id,
        user_id=channel.user_id,
        channel_type=channel.channel_type,
        config=_parse_settings_json(channel.config),
        enabled=bool(channel.enabled),
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_channel(
    channel_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete an alert channel."""
    result = await session.execute(
        select(AlertChannel).where(
            AlertChannel.id == channel_id,
            AlertChannel.user_id == current_user.id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert channel not found",
        )

    await session.delete(channel)
    await session.commit()
