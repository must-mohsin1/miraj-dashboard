"""Settings routes — CRUD for user pair settings and alert channels.

Endpoints
---------
GET    /api/v1/settings/pairs           — list all pair settings for the current user
PUT    /api/v1/settings/pairs/{pair}    — update pair settings (alert_threshold, alert_enabled, etc.)
GET    /api/v1/settings/channels        — list all alert channels for the current user
POST   /api/v1/settings/channels        — create a new alert channel (Telegram / Discord)
PUT    /api/v1/settings/channels/{id}   — update an alert channel config
DELETE /api/v1/settings/channels/{id}   — delete an alert channel
GET    /api/v1/settings/email           — get the user's alert email address
POST   /api/v1/settings/email           — save / update the user's alert email address
POST   /api/v1/settings/email/test      — send a test email to the configured address
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


# ── Email Alert Settings ────────────────────────────────────────────────────
#
# Stores the user's alert email address as an ``AlertChannel`` row with
# ``channel_type="email"`` and ``config={"email": "user@example.com", "alerts_enabled": true}``.
# This reuses the existing channels table rather than adding a column to User.


class EmailSettingsResponse(BaseModel):
    """Response body for GET /api/v1/settings/email."""

    email: Optional[str] = None
    alerts_enabled: bool = False


class EmailSettingsUpdateRequest(BaseModel):
    """Request body for POST /api/v1/settings/email."""

    email: Optional[str] = Field(
        default=None,
        description="Email address for alerts. Set to null or empty to clear.",
    )
    alerts_enabled: bool = Field(
        default=True,
        description="Whether email alerts are enabled for this user.",
    )


class EmailTestResponse(BaseModel):
    """Response body for POST /api/v1/settings/email/test."""

    ok: bool
    error: Optional[str] = None


def _get_email_channel(user: User, session: AsyncSession):
    """Fetch the user's email alert channel (lazy — returns a coroutine)."""
    return session.execute(
        select(AlertChannel).where(
            AlertChannel.user_id == user.id,
            AlertChannel.channel_type == "email",
        )
    )


@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_settings(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EmailSettingsResponse:
    """Get the user's saved alert email address and enabled status."""
    result = await _get_email_channel(current_user, session)
    channel = result.scalar_one_or_none()

    if not channel:
        return EmailSettingsResponse(email=None, alerts_enabled=False)

    config = _parse_settings_json(channel.config)
    return EmailSettingsResponse(
        email=config.get("email"),
        alerts_enabled=bool(channel.enabled),
    )


@router.post("/email", response_model=EmailSettingsResponse)
async def update_email_settings(
    body: EmailSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EmailSettingsResponse:
    """Save or update the user's alert email address.

    Creates an ``email``-type AlertChannel if none exists, otherwise updates
    the existing one. Pass ``email: null`` to clear the address.
    """
    # Validate email syntax if a non-empty address is provided.
    if body.email:
        from email_validator import EmailNotValidError, validate_email

        try:
            validated = validate_email(body.email, check_deliverability=False)
            normalized = validated.normalized
        except EmailNotValidError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid email address format",
            )
    else:
        normalized = None

    result = await _get_email_channel(current_user, session)
    channel = result.scalar_one_or_none()

    config = {"email": normalized}

    if channel:
        channel.config = json.dumps(config)
        channel.enabled = 1 if body.alerts_enabled else 0
        channel.updated_at = datetime.utcnow()
    else:
        channel = AlertChannel(
            user_id=current_user.id,
            channel_type="email",
            config=json.dumps(config),
            enabled=1 if body.alerts_enabled else 0,
        )
        session.add(channel)

    await session.commit()
    await session.refresh(channel)

    return EmailSettingsResponse(
        email=normalized,
        alerts_enabled=bool(channel.enabled),
    )


@router.post("/email/test", response_model=EmailTestResponse)
async def send_test_email_route(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EmailTestResponse:
    """Send a test email to the user's configured alert email address.

    Returns ``{ok: true}`` on success or ``{ok: false, error: "..."}`` on
    failure (e.g. SMTP not configured).
    """
    result = await _get_email_channel(current_user, session)
    channel = result.scalar_one_or_none()

    if not channel:
        return EmailTestResponse(
            ok=False, error="No email address configured. Set one first."
        )

    config = _parse_settings_json(channel.config)
    recipient = config.get("email")

    if not recipient:
        return EmailTestResponse(
            ok=False, error="No email address configured. Set one first."
        )

    success = await _send_email_safe(recipient)
    return EmailTestResponse(ok=success, error=None if success else "SMTP send failed")


async def _send_email_safe(recipient: str) -> bool:
    """Wrap the test email send so import / config errors don't crash the route."""
    try:
        from backend.services.email_service import send_test_email

        return await send_test_email(recipient)
    except ImportError:
        return False
    except Exception as exc:
        logger.error("Test email to %s failed: %s", recipient, exc)
        return False
