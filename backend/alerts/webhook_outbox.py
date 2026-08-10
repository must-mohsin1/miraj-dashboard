"""Durable, leased outbox for signed scan-signal webhook delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import datetime
import hashlib
import json
import logging
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.alerts.webhook import (
    WebhookDeliveryResult,
    build_signal_delivery_id,
    send_signal_webhook,
    serialize_payload,
)
from backend.database import get_session_factory
from backend.models import AlertChannel, AlertHistory, SignalWebhookDelivery


logger = logging.getLogger(__name__)

MAX_PENDING_PER_USER = 100
DISPATCH_BATCH_SIZE = 20
DISPATCH_CONCURRENCY = 4
DISPATCH_JOB_TIMEOUT_SECONDS = 55
MAX_DELIVERY_ATTEMPTS = 8
DELIVERY_LEASE_SECONDS = 30
TERMINAL_RETENTION_DAYS = 30


@dataclass(frozen=True)
class QueuedSignalWebhook:
    delivery_id: str
    created: bool
    status: str = "pending"


def build_webhook_config_fingerprint(webhook_url: str, signing_secret: str) -> str:
    """Bind queued work to a destination/secret generation without storing secrets."""
    canonical = json.dumps(
        {"signing_secret": signing_secret, "webhook_url": webhook_url},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


async def enqueue_signal_webhook(
    *,
    user_id: int,
    channel_id: int,
    pair: str,
    direction: str,
    score: float,
    payload: dict[str, Any],
    webhook_url: str,
    signing_secret: str,
) -> QueuedSignalWebhook | None:
    """Commit one idempotent outbox row without using the scan transaction."""
    delivery_id = build_signal_delivery_id(
        user_id=user_id,
        channel_id=channel_id,
        payload=payload,
    )
    payload_text = serialize_payload(payload).decode("utf-8")
    config_fingerprint = build_webhook_config_fingerprint(
        webhook_url,
        signing_secret,
    )
    factory = get_session_factory()
    async with factory() as session:
        # SQLite is the supported database. Serialize the count-and-insert so
        # the per-user queue cap remains hard under concurrent scan workers.
        await session.execute(text("BEGIN IMMEDIATE"))
        existing = (
            await session.execute(
                select(
                    SignalWebhookDelivery.id,
                    SignalWebhookDelivery.status,
                ).where(
                    SignalWebhookDelivery.channel_id == channel_id,
                    SignalWebhookDelivery.delivery_id == delivery_id,
                    SignalWebhookDelivery.config_fingerprint == config_fingerprint,
                )
            )
        ).one_or_none()
        if existing is not None and existing.status in {
            "pending",
            "processing",
            "sent",
        }:
            return QueuedSignalWebhook(
                delivery_id=delivery_id,
                created=False,
                status=str(existing.status),
            )

        pending_count = await session.scalar(
            select(func.count(SignalWebhookDelivery.id)).where(
                SignalWebhookDelivery.user_id == user_id,
                SignalWebhookDelivery.status.in_(("pending", "processing")),
            )
        )
        if int(pending_count or 0) >= MAX_PENDING_PER_USER:
            logger.warning(
                "Signal webhook queue limit reached for user %d; delivery skipped",
                user_id,
            )
            return None

        if existing is not None:
            redrive = await session.execute(
                update(SignalWebhookDelivery)
                .where(
                    SignalWebhookDelivery.id == existing.id,
                    SignalWebhookDelivery.status.in_(("failed", "cancelled")),
                )
                .values(
                    status="pending",
                    attempts=0,
                    next_attempt_at=None,
                    lease_expires_at=None,
                    last_status_code=None,
                    last_error=None,
                    sent_at=None,
                )
            )
            await session.commit()
            return QueuedSignalWebhook(
                delivery_id=delivery_id,
                created=False,
                status="pending" if redrive.rowcount == 1 else str(existing.status),
            )

        statement = (
            sqlite_insert(SignalWebhookDelivery)
            .values(
                user_id=user_id,
                channel_id=channel_id,
                pair=pair,
                direction=direction,
                score=score,
                delivery_id=delivery_id,
                payload=payload_text,
                config_fingerprint=config_fingerprint,
                status="pending",
                attempts=0,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "channel_id",
                    "delivery_id",
                    "config_fingerprint",
                ],
            )
        )
        result = await session.execute(statement)
        await session.commit()
        return QueuedSignalWebhook(
            delivery_id=delivery_id,
            created=result.rowcount == 1,
        )


def _eligible_delivery(now: datetime.datetime):
    return or_(
        and_(
            SignalWebhookDelivery.status == "pending",
            or_(
                SignalWebhookDelivery.next_attempt_at.is_(None),
                SignalWebhookDelivery.next_attempt_at <= now,
            ),
        ),
        and_(
            SignalWebhookDelivery.status == "processing",
            or_(
                SignalWebhookDelivery.lease_expires_at.is_(None),
                SignalWebhookDelivery.lease_expires_at <= now,
            ),
        ),
    )


async def dispatch_pending_signal_webhooks(session_factory=None) -> int:
    """Fairly claim due rows and deliver them without holding DB locks over I/O."""
    factory = session_factory or get_session_factory()
    now = datetime.datetime.utcnow()
    async with factory() as session:
        ranked = (
            select(
                SignalWebhookDelivery.id.label("id"),
                SignalWebhookDelivery.user_id.label("user_id"),
                SignalWebhookDelivery.created_at.label("created_at"),
                func.row_number()
                .over(
                    partition_by=SignalWebhookDelivery.user_id,
                    order_by=(
                        SignalWebhookDelivery.created_at.asc(),
                        SignalWebhookDelivery.id.asc(),
                    ),
                )
                .label("user_rank"),
            )
            .where(_eligible_delivery(now))
            .subquery()
        )
        delivery_ids = list(
            (
                await session.execute(
                    select(ranked.c.id)
                    .order_by(
                        ranked.c.user_rank.asc(),
                        ranked.c.created_at.asc(),
                        ranked.c.id.asc(),
                    )
                    .limit(DISPATCH_BATCH_SIZE)
                )
            ).scalars()
        )

    admission = asyncio.Semaphore(DISPATCH_CONCURRENCY)

    async def _dispatch_safely(delivery_row_id: int) -> bool:
        try:
            async with admission:
                return await _dispatch_one(factory, delivery_row_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Signal webhook outbox row %d failed unexpectedly; lease will recover it",
                delivery_row_id,
            )
            return False

    tasks = [
        asyncio.create_task(_dispatch_safely(delivery_row_id))
        for delivery_row_id in delivery_ids
    ]
    if not tasks:
        return 0
    done, pending = await asyncio.wait(
        tasks,
        timeout=DISPATCH_JOB_TIMEOUT_SECONDS,
    )
    if pending:
        logger.warning(
            "Signal webhook dispatch deadline reached; %d lease(s) will recover",
            len(pending),
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return sum(task.result() is True for task in done if not task.cancelled())


async def cleanup_terminal_signal_webhooks(session_factory=None) -> int:
    """Delete terminal outbox payloads after the bounded audit window."""
    factory = session_factory or get_session_factory()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(
        days=TERMINAL_RETENTION_DAYS
    )
    async with factory() as session:
        result = await session.execute(
            delete(SignalWebhookDelivery).where(
                SignalWebhookDelivery.status.in_(("sent", "failed", "cancelled")),
                SignalWebhookDelivery.created_at < cutoff,
            )
        )
        await session.commit()
        return int(result.rowcount or 0)


async def _dispatch_one(session_factory, delivery_row_id: int) -> bool:
    now = datetime.datetime.utcnow()
    lease_until = now + datetime.timedelta(seconds=DELIVERY_LEASE_SECONDS)

    async with session_factory() as session:
        claim = await session.execute(
            update(SignalWebhookDelivery)
            .where(
                SignalWebhookDelivery.id == delivery_row_id,
                _eligible_delivery(now),
            )
            .values(
                status="processing",
                attempts=SignalWebhookDelivery.attempts + 1,
                lease_expires_at=lease_until,
            )
        )
        if claim.rowcount != 1:
            await session.rollback()
            return False
        row = await session.get(SignalWebhookDelivery, delivery_row_id)
        channel = await session.get(AlertChannel, row.channel_id) if row else None
        if row is None:
            await session.rollback()
            return False
        attempts = int(row.attempts)
        user_id = int(row.user_id)
        pair = str(row.pair)
        direction = str(row.direction)
        score = float(row.score) if row.score is not None else None
        delivery_id = str(row.delivery_id)
        payload_text = str(row.payload)
        config_fingerprint = str(row.config_fingerprint)
        channel_enabled = bool(channel and channel.enabled)
        channel_type = str(channel.channel_type) if channel else "webhook"
        channel_user_id = int(channel.user_id) if channel else None
        raw_config = channel.config if channel else None
        await session.commit()

    if channel_user_id != user_id:
        await _finalize_without_attempt(
            session_factory,
            delivery_row_id,
            lease_until=lease_until,
            status="cancelled",
            error="channel_owner_mismatch",
        )
        return True

    if not channel_enabled or channel_type != "webhook":
        await _finalize_without_attempt(
            session_factory,
            delivery_row_id,
            lease_until=lease_until,
            status="cancelled",
            error="channel_unavailable",
        )
        return True

    try:
        config = json.loads(raw_config or "{}")
        payload = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        config = {}
        payload = {}

    if not isinstance(config, dict) or not isinstance(payload, dict):
        result = WebhookDeliveryResult(
            False,
            delivery_id,
            error="invalid_config",
        )
    else:
        webhook_url = config.get("webhook_url")
        signing_secret = config.get("signing_secret")
        if not isinstance(webhook_url, str) or not isinstance(signing_secret, str):
            result = WebhookDeliveryResult(
                False,
                delivery_id,
                error="invalid_config",
            )
        elif (
            build_webhook_config_fingerprint(webhook_url, signing_secret)
            != config_fingerprint
        ):
            await _finalize_without_attempt(
                session_factory,
                delivery_row_id,
                lease_until=lease_until,
                status="cancelled",
                error="channel_config_changed",
            )
            return True
        else:
            try:
                result = await send_signal_webhook(
                    webhook_url=webhook_url,
                    signing_secret=signing_secret,
                    payload=payload,
                    delivery_id=delivery_id,
                )
            except Exception:
                logger.exception(
                    "Signal webhook transport raised unexpectedly (delivery_id=%s)",
                    delivery_id,
                )
                result = WebhookDeliveryResult(
                    False,
                    delivery_id,
                    error="transport_error",
                )

    await _record_attempt(
        session_factory=session_factory,
        delivery_row_id=delivery_row_id,
        lease_until=lease_until,
        attempts=attempts,
        user_id=user_id,
        pair=pair,
        direction=direction,
        score=score,
        payload=payload,
        result=result,
    )
    return True


async def _finalize_without_attempt(
    session_factory,
    delivery_row_id: int,
    *,
    lease_until: datetime.datetime,
    status: str,
    error: str,
) -> None:
    async with session_factory() as session:
        row = await session.get(SignalWebhookDelivery, delivery_row_id)
        if (
            row is None
            or row.status != "processing"
            or row.lease_expires_at != lease_until
        ):
            return
        row.status = status
        row.last_error = error
        row.lease_expires_at = None
        await session.commit()


async def _record_attempt(
    *,
    session_factory,
    delivery_row_id: int,
    lease_until: datetime.datetime,
    attempts: int,
    user_id: int,
    pair: str,
    direction: str,
    score: float | None,
    payload: dict[str, Any],
    result: WebhookDeliveryResult,
) -> None:
    now = datetime.datetime.utcnow()
    permanent_http_error = (
        result.status_code is not None
        and 400 <= result.status_code < 500
        and result.status_code not in {408, 429}
    )
    permanent_error = result.error in {
        "invalid_config",
        "invalid_payload",
    }

    async with session_factory() as session:
        row = await session.get(SignalWebhookDelivery, delivery_row_id)
        if (
            row is None
            or row.status != "processing"
            or row.lease_expires_at != lease_until
        ):
            return
        row.last_status_code = result.status_code
        row.last_error = result.error
        row.lease_expires_at = None
        if result.success:
            row.status = "sent"
            row.sent_at = now
            row.next_attempt_at = None
        elif (
            permanent_http_error or permanent_error or attempts >= MAX_DELIVERY_ATTEMPTS
        ):
            row.status = "failed"
            row.next_attempt_at = None
        else:
            row.status = "pending"
            row.next_attempt_at = now + datetime.timedelta(
                seconds=2 ** min(attempts, 7)
            )

        session.add(
            AlertHistory(
                user_id=user_id,
                pair=pair,
                channel="webhook",
                score=score,
                direction=direction,
                message=json.dumps(
                    {
                        "delivery_id": result.delivery_id,
                        "event": payload,
                        "status_code": result.status_code,
                        "error": result.error,
                        "attempt": attempts,
                    },
                    default=str,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                status="sent" if result.success else "failed",
            )
        )
        await session.commit()
