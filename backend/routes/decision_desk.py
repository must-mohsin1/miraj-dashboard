"""Read-only Decision Desk snapshot of watchlist, delivery, and account-cache evidence."""

from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import (
    AlertChannel,
    ExchangeKey,
    PortfolioPosition,
    PortfolioSnapshot,
    RealtimeNotification,
    RealtimeSignal,
    User,
    WatchlistPair,
)
from backend.realtime.mexc_contracts import classify_market_scope, fetch_mexc_contract_catalogue
from backend.schemas import (
    DecisionDeskAccountPosition,
    DecisionDeskAccountReconciliation,
    DecisionDeskNotificationChannel,
    DecisionDeskNotificationOutboxItem,
    DecisionDeskResponse,
    DecisionDeskSetupAnalysis,
    DecisionDeskSignal,
    DecisionDeskWatchlistPair,
)

router = APIRouter(prefix="/api/v1/decision-desk", tags=["decision-desk"])
_RECONCILIATION_FRESH_SECONDS = 5 * 60


def _missing_gates(value: str | None) -> list[str]:
    """Decode the durable gate list without allowing malformed historical data to fail the snapshot."""
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [gate for gate in decoded if isinstance(gate, str)] if isinstance(decoded, list) else []


def _setup_analysis(value: str | None) -> DecisionDeskSetupAnalysis | None:
    """Decode only complete, numeric setup evidence from the persisted signal."""
    try:
        decoded = json.loads(value or "{}")
        return DecisionDeskSetupAnalysis.model_validate(decoded)
    except (TypeError, ValueError):
        return None


def _channel_is_configured(channel: AlertChannel) -> bool:
    """Confirm required channel settings exist without returning those settings."""
    try:
        config = json.loads(channel.config or "{}")
    except (TypeError, ValueError):
        return False
    if not isinstance(config, dict):
        return False
    if channel.channel_type == "telegram":
        return bool(config.get("chat_id"))
    if channel.channel_type == "discord":
        return bool(config.get("webhook_url"))
    return False


def _safe_notification_error(value: str | None) -> str | None:
    """Keep delivery diagnostics useful while preventing URL/token leakage."""
    if not value:
        return None
    redacted = re.sub(r"https?://\S+", "[redacted-url]", value)
    redacted = re.sub(
        r"(?i)\b(chat[_-]?id|token|secret|api[_-]?key|authorization)\b\s*([=:])\s*[^\s,;]+",
        r"\1\2[redacted]",
        redacted,
    )
    return redacted[:200]


@router.get("/now", response_model=DecisionDeskResponse)
async def now(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionDeskResponse:
    """Return current-user persisted evidence only; never refresh accounts or infer signals."""
    watchlist_result = await session.execute(
        select(WatchlistPair)
        .where(WatchlistPair.user_id == current_user.id)
        .order_by(WatchlistPair.sort_order.asc())
    )
    signal_result = await session.execute(
        select(RealtimeSignal)
        .where(RealtimeSignal.user_id == current_user.id)
        .order_by(RealtimeSignal.updated_at.desc(), RealtimeSignal.id.desc())
    )
    channel_result = await session.execute(
        select(AlertChannel)
        .where(AlertChannel.user_id == current_user.id)
        .order_by(AlertChannel.created_at.asc(), AlertChannel.id.asc())
    )
    outbox_result = await session.execute(
        select(RealtimeNotification, RealtimeSignal, AlertChannel)
        .join(RealtimeSignal, RealtimeNotification.signal_id == RealtimeSignal.id)
        .join(AlertChannel, RealtimeNotification.channel_id == AlertChannel.id)
        .where(
            RealtimeSignal.user_id == current_user.id,
            AlertChannel.user_id == current_user.id,
        )
        .order_by(RealtimeNotification.created_at.desc(), RealtimeNotification.id.desc())
        .limit(100)
    )
    snapshot_result = await session.execute(
        select(PortfolioSnapshot.exchange, PortfolioSnapshot.timestamp)
        .where(PortfolioSnapshot.user_id == current_user.id)
        .order_by(PortfolioSnapshot.exchange.asc(), PortfolioSnapshot.timestamp.desc())
    )
    positions_result = await session.execute(
        select(PortfolioPosition)
        .where(PortfolioPosition.user_id == current_user.id)
        .order_by(PortfolioPosition.exchange.asc(), PortfolioPosition.symbol.asc())
    )
    configured_exchange_result = await session.execute(
        select(ExchangeKey.exchange)
        .where(ExchangeKey.user_id == current_user.id)
        .order_by(ExchangeKey.exchange.asc())
    )
    catalogue = await fetch_mexc_contract_catalogue()

    watchlist = []
    for pair in watchlist_result.scalars():
        market_scope, mexc_symbol = classify_market_scope(pair.pair, catalogue)
        watchlist.append(
            DecisionDeskWatchlistPair(
                pair=pair.pair,
                market_scope=market_scope,
                mexc_symbol=mexc_symbol,
            )
        )

    signals = [
        DecisionDeskSignal(
            pair=signal.pair,
            direction=signal.direction,
            state=signal.state,
            missing_gates=_missing_gates(signal.missing_gates),
            analysis=_setup_analysis(signal.analysis_json),
            created_at=signal.created_at,
            updated_at=signal.updated_at,
        )
        for signal in signal_result.scalars()
    ]
    notification_channels = [
        DecisionDeskNotificationChannel(
            channel_type=channel.channel_type,
            enabled=bool(channel.enabled),
            configured=_channel_is_configured(channel),
            updated_at=channel.updated_at,
        )
        for channel in channel_result.scalars()
    ]
    notification_outbox = [
        DecisionDeskNotificationOutboxItem(
            pair=signal.pair,
            direction=signal.direction,
            signal_state=signal.state,
            channel_type=channel.channel_type,
            status=notification.status,
            attempts=notification.attempts,
            created_at=notification.created_at,
            next_attempt_at=notification.next_attempt_at,
            sent_at=notification.sent_at,
            error=_safe_notification_error(notification.last_error),
        )
        for notification, signal, channel in outbox_result.all()
    ]

    # A snapshot is written only after the authenticated, read-only portfolio
    # refresh succeeds. This endpoint never refreshes an account or loads keys.
    latest_snapshot_by_exchange: dict[str, datetime] = {}
    for exchange, timestamp in snapshot_result.all():
        latest_snapshot_by_exchange.setdefault(exchange, timestamp)
    positions_by_exchange: dict[str, list[DecisionDeskAccountPosition]] = {}
    for position in positions_result.scalars():
        positions_by_exchange.setdefault(str(position.exchange), []).append(
            DecisionDeskAccountPosition(
                symbol=str(position.symbol), side=str(position.side), size=float(position.size)
            )
        )
    exchanges = sorted(
        set(configured_exchange_result.scalars())
        | set(latest_snapshot_by_exchange)
        | set(positions_by_exchange)
    )
    generated_at = datetime.utcnow()
    account_reconciliation = []
    for exchange in exchanges:
        last_reconciled_at = latest_snapshot_by_exchange.get(exchange)
        freshness = "unavailable"
        if last_reconciled_at is not None:
            age_seconds = (generated_at - last_reconciled_at).total_seconds()
            freshness = "fresh" if age_seconds <= _RECONCILIATION_FRESH_SECONDS else "stale"
        account_reconciliation.append(
            DecisionDeskAccountReconciliation(
                exchange=exchange,
                freshness=freshness,
                last_reconciled_at=last_reconciled_at,
                positions=positions_by_exchange.get(exchange, []),
            )
        )
    return DecisionDeskResponse(
        generated_at=generated_at,
        watchlist=watchlist,
        signals=signals,
        notification_channels=notification_channels,
        notification_outbox=notification_outbox,
        account_reconciliation=account_reconciliation,
    )
