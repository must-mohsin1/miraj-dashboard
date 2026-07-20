"""Durable state transitions for real-time advisory signals."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AlertChannel, RealtimeNotification, RealtimeSignal
from backend.realtime.lifecycle import SignalEvaluation


@dataclass(frozen=True)
class StoredTransition:
    changed: bool
    signal: RealtimeSignal


async def record_transition(
    session: AsyncSession,
    user_id: int,
    pair: str,
    direction: str,
    evaluation: SignalEvaluation,
) -> StoredTransition:
    """Upsert one lifecycle state and report whether it actually changed.

    The caller sends a notification only when ``changed`` is true, so repeated
    websocket ticks and a worker restart cannot resend an unchanged state.
    """
    normalized_pair = pair.strip().upper()
    normalized_direction = direction.strip().upper()
    row = (
        await session.execute(
            select(RealtimeSignal).where(
                RealtimeSignal.user_id == user_id,
                RealtimeSignal.pair == normalized_pair,
                RealtimeSignal.direction == normalized_direction,
            )
        )
    ).scalar_one_or_none()
    missing_gates = json.dumps(evaluation.missing_gates)
    analysis_json = json.dumps(asdict(evaluation.analysis)) if evaluation.analysis else None

    if row is None:
        row = RealtimeSignal(
            user_id=user_id,
            pair=normalized_pair,
            direction=normalized_direction,
            state=evaluation.state.value,
            dedup_key=f"{evaluation.dedup_key}:1",
            transition_count=1,
            missing_gates=missing_gates,
            analysis_json=analysis_json,
        )
        session.add(row)
        await session.flush()
        return StoredTransition(changed=True, signal=row)

    changed = row.state != evaluation.state.value
    row.missing_gates = missing_gates
    row.analysis_json = analysis_json
    if changed:
        row.state = evaluation.state.value
        row.transition_count += 1
        row.dedup_key = f"{evaluation.dedup_key}:{row.transition_count}"
    await session.flush()
    return StoredTransition(changed=changed, signal=row)


async def enqueue_transition_notifications(
    session: AsyncSession, signal: RealtimeSignal, evaluation: SignalEvaluation
) -> None:
    """Create committed pending delivery records before any network call."""
    # STALE is persisted for audit and shown in the Decision Desk, but it is
    # deliberately not pushed as a trade alert. A silent/expired feed contains
    # no current market thesis and must not resemble a decision-ready setup.
    if evaluation.state.value not in {"ACTIONABLE", "INVALIDATED"}:
        return
    channels = (
        await session.execute(
            select(AlertChannel).where(AlertChannel.user_id == signal.user_id, AlertChannel.enabled == 1)
        )
    ).scalars()
    for channel in channels:
        existing = await session.scalar(
            select(RealtimeNotification.id).where(
                RealtimeNotification.signal_id == signal.id,
                RealtimeNotification.channel_id == channel.id,
                RealtimeNotification.dedup_key == signal.dedup_key,
            )
        )
        if existing is None:
            session.add(
                RealtimeNotification(
                    signal_id=signal.id,
                    channel_id=channel.id,
                    dedup_key=signal.dedup_key,
                )
            )
    await session.flush()
