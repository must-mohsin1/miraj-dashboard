"""Alert manager — orchestrator for trade alert dispatch.

Responsibilities
----------------
1. **Threshold filtering** — only send alerts when ``confluence_score >=``
   the user's per-pair threshold (from ``PairSetting.settings``).
2. **Dedup** — skip symbols already alerted within the cooldown period
   (configurable per-channel via ``ALERT_COOLDOWN_HOURS``, default 4h).
3. **Channel routing** — iterate over the user's enabled ``AlertChannel``
   rows and deliver via Telegram, Discord, email, or signed webhook.
4. **Webhook queueing** — commit signed webhook work before network delivery.
5. **History logging** — persist every actual send attempt to ``AlertHistory``.

Typical usage (inside the scheduled scan)::

    from backend.alerts.manager import process_scan_results

    await process_scan_results(session, scan_results_by_user)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    AlertChannel,
    AlertHistory,
    PairSetting,
    SignalWebhookDelivery,
    User,
)
from backend.alerts.email import build_email_body, send_email
from backend.alerts.telegram import format_alert_message, send_alert
from backend.alerts.discord import build_embed, send_webhook
from backend.alerts.webhook import build_signal_event
from backend.alerts.webhook_outbox import enqueue_signal_webhook

logger = logging.getLogger(__name__)

# ── Defaults (overridable via PairSetting.settings or environment) ───────────
DEFAULT_THRESHOLD = 60.0
DEFAULT_COOLDOWN_HOURS = 4


# ── Public API ──────────────────────────────────────────────────────────────


async def process_scan_results(
    session: AsyncSession,
    results_by_user: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Evaluate each user's scan results and deliver alerts as needed.

    *results_by_user* maps ``user_id`` → list of scan result dicts
    (each with at least ``symbol``, ``confluence_score``, ``trade_plan``).

    Returns a list of outcome dicts for audit / logging::

        [
          {"user_id": 1, "pair": "BTC-USD", "score": 75.0,
           "channels_sent": ["telegram"], "status": "sent"},
          ...
        ]
    """
    outcomes: list[dict[str, Any]] = []

    for user_id, results in results_by_user.items():
        # Fetch user's alert channels and pair settings in bulk
        channels = await _get_enabled_channels(session, user_id)
        if not channels:
            logger.debug("User %d has no enabled alert channels; skipping", user_id)
            continue

        pair_settings_map = await _get_pair_settings_map(session, user_id)
        alerted_pairs: set[str] = set()

        for scan_result in results:
            raw_symbol = (
                scan_result.get("symbol") if isinstance(scan_result, dict) else None
            )
            normalized_symbol = (
                raw_symbol.strip().upper() if isinstance(raw_symbol, str) else ""
            )
            if normalized_symbol and normalized_symbol in alerted_pairs:
                logger.info(
                    "Symbol %s for user %d was already handled in this batch; skipping",
                    normalized_symbol,
                    user_id,
                )
                continue
            try:
                outcome = await _process_single_result(
                    session,
                    user_id,
                    scan_result,
                    channels,
                    pair_settings_map,
                )
            except Exception:
                logger.exception(
                    "Alert result processing failed for user %d; continuing batch",
                    user_id,
                )
                continue
            if outcome:
                outcomes.append(outcome)
                if outcome.get("channels_sent") or outcome.get("channels_queued"):
                    alerted_pairs.add(str(outcome["pair"]))

    return outcomes


# ── Internal helpers ──────────────────────────────────────────────────────────


def is_actionable_trade_plan(trade_plan: Any) -> bool:
    """Return whether a scan explicitly confirmed a manual-entry trade plan.

    A confluence score is context, not a trade trigger.  Scheduled alerts must
    never notify a user of an actionable setup unless the analysis pipeline set
    ``trade_decision`` to the literal boolean ``True``.
    """
    return isinstance(trade_plan, dict) and trade_plan.get("trade_decision") is True


async def _get_enabled_channels(
    session: AsyncSession,
    user_id: int,
) -> list[AlertChannel]:
    """Return all enabled AlertChannel rows for *user_id*."""
    with session.no_autoflush:
        result = await session.execute(
            select(AlertChannel).where(
                AlertChannel.user_id == user_id,
                AlertChannel.enabled == 1,
            )
        )
    return list(result.scalars().all())


async def _get_pair_settings_map(
    session: AsyncSession,
    user_id: int,
) -> dict[str, dict[str, Any]]:
    """Return a dict of ``pair → full settings dict`` from PairSetting rows.

    Returns the parsed JSON ``settings`` dict for every pair that has one.
    Callers access ``alert_threshold`` and ``alert_enabled`` from the value::

        info = settings_map.get(symbol, {})
        threshold = info.get("alert_threshold") or DEFAULT_THRESHOLD
        enabled = info.get("alert_enabled", True)
    """
    with session.no_autoflush:
        result = await session.execute(
            select(PairSetting).where(PairSetting.user_id == user_id)
        )
    settings_map: dict[str, dict[str, Any]] = {}
    for ps in result.scalars().all():
        if not ps.settings:
            continue
        try:
            settings = json.loads(ps.settings)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(settings, dict):
            settings_map[ps.pair.upper()] = settings
    return settings_map


async def _process_single_result(
    session: AsyncSession,
    user_id: int,
    scan_result: dict[str, Any],
    channels: list[AlertChannel],
    pair_settings_map: dict[str, dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Evaluate one scan result and deliver alerts if thresholds are met.

    Returns an outcome dict or ``None`` if no alert was needed.
    """
    raw_symbol = scan_result.get("symbol")
    symbol = raw_symbol.strip().upper() if isinstance(raw_symbol, str) else ""
    if not symbol:
        logger.warning("Scan result missing symbol; skipping")
        return None

    # A confluence score alone is only a watch condition.  Manual-entry
    # notifications require an explicit confirmation from the trade plan.
    trade_plan = scan_result.get("trade_plan", {}) or {}
    if not is_actionable_trade_plan(trade_plan):
        logger.debug("Symbol %s has no confirmed trade decision; no alert", symbol)
        return None

    raw_score = (
        scan_result.get("confluence_score") or scan_result.get("overall_score") or 0.0
    )
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        logger.warning("Scan result for %s has an invalid score; skipping", symbol)
        return None
    if not math.isfinite(score):
        logger.warning("Scan result for %s has a non-finite score; skipping", symbol)
        return None

    # ── Fetch pair-specific settings ──────────────────────────────────
    pair_settings = pair_settings_map.get(symbol, {})

    # ── Check alert_enabled ───────────────────────────────────────────
    # Use truthiness check (not identity 'is False') so that any falsy
    # value (False, 0, None, "") correctly disables alerts.
    if not pair_settings.get("alert_enabled", True):
        logger.debug(
            "Alert disabled for %s (user %d) via pair settings",
            symbol,
            user_id,
        )
        return None

    # ── Threshold check ─────────────────────────────────────────────
    try:
        threshold = float(pair_settings.get("alert_threshold") or DEFAULT_THRESHOLD)
    except (TypeError, ValueError):
        logger.warning(
            "Alert threshold for %s (user %d) is invalid; skipping",
            symbol,
            user_id,
        )
        return None
    if not math.isfinite(threshold):
        logger.warning(
            "Alert threshold for %s (user %d) is non-finite; skipping",
            symbol,
            user_id,
        )
        return None
    if score < threshold:
        logger.debug(
            "Symbol %s score %.1f < threshold %.1f for user %d; no alert",
            symbol,
            score,
            threshold,
            user_id,
        )
        return None

    # ── Extract trade plan details ──────────────────────────────────
    trade_plan = scan_result.get("trade_plan", {}) or {}
    flat_plan = scan_result.get("trade_plan_flat", {}) or {}
    if not isinstance(flat_plan, dict):
        flat_plan = {}
    raw_direction = flat_plan.get("direction") or trade_plan.get("direction")
    if not isinstance(raw_direction, str):
        logger.warning("Confirmed trade plan for %s has no direction; skipping", symbol)
        return None
    direction = raw_direction.strip().upper()
    if direction not in {"LONG", "SHORT"}:
        logger.warning(
            "Confirmed trade plan for %s has unsupported direction %r; skipping",
            symbol,
            raw_direction,
        )
        return None
    entry = _extract_float(flat_plan, "entry")
    if entry is None:
        entry = _extract_float(trade_plan, "entry")
    stop_loss = _extract_float(flat_plan, "stop_loss")
    if stop_loss is None:
        stop_loss = _extract_float(trade_plan, "stop_loss")
    target = _extract_float(flat_plan, "target_1")
    if target is None:
        target = _extract_float(flat_plan, "tp1_price")
    if target is None:
        target = _extract_float(trade_plan, "target_1")
    if target is None:
        target = _extract_float(trade_plan, "target")
    rationale = (
        flat_plan.get("rationale")
        or trade_plan.get("reasoning")
        or trade_plan.get("rationale")
        or trade_plan.get("verdict")
    )
    if isinstance(rationale, str):
        rationale = rationale[:200]  # keep it short
    else:
        rationale = None
    signal_time = _parse_signal_time(scan_result.get("cached_at"))

    # ── Build messages ──────────────────────────────────────────────
    tg_text = format_alert_message(
        symbol=symbol,
        score=score,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        target=target,
        rationale=rationale,
    )
    dc_embed = build_embed(
        symbol=symbol,
        score=score,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        target=target,
        rationale=rationale,
    )

    # ── Cooldown check (per symbol, per user) ───────────────────────
    cooldown_hours = DEFAULT_COOLDOWN_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)

    recent_count = await _count_recent_alerts(session, user_id, symbol, cutoff)
    if recent_count > 0:
        logger.info(
            "Symbol %s for user %d was alerted %d time(s) in last %dh; skipping",
            symbol,
            user_id,
            recent_count,
            cooldown_hours,
        )
        return None

    # ── Per-pair notification channel filter ─────────────────────────
    notification_channels = pair_settings.get("notification_channels")
    if isinstance(notification_channels, list) and notification_channels:
        # Only deliver to channels whose type is in the user's explicit list
        filtered = [ch for ch in channels if ch.channel_type in notification_channels]
        if not filtered:
            logger.debug(
                "Pair %s for user %d specifies channels=%s but none match enabled channels; "
                "sending nothing",
                symbol,
                user_id,
                notification_channels,
            )
            return None
        channels = filtered

    # ── Deliver to each enabled channel ─────────────────────────────
    channels_sent: list[str] = []
    channels_queued: list[str] = []
    for ch in channels:
        try:
            config = json.loads(ch.config) if ch.config else {}
        except (json.JSONDecodeError, TypeError):
            config = {}
        if not isinstance(config, dict):
            config = {}

        success = False
        queued = False
        message_log = ""
        try:
            if ch.channel_type == "telegram":
                chat_id = config.get("chat_id")
                if chat_id:
                    success = await send_alert(str(chat_id), tg_text)
                    message_log = tg_text
                else:
                    logger.warning(
                        "Telegram channel %d (user %d) is missing chat_id in config; skipping",
                        ch.id,
                        user_id,
                    )
            elif ch.channel_type == "discord":
                webhook_url = config.get("webhook_url")
                if webhook_url:
                    success = await send_webhook(str(webhook_url), dc_embed)
                    message_log = str(dc_embed)
                else:
                    logger.warning(
                        "Discord channel %d (user %d) is missing webhook_url in config; skipping",
                        ch.id,
                        user_id,
                    )
            elif ch.channel_type == "email":
                email_to = config.get("email_to")
                if email_to:
                    email_body = build_email_body(
                        symbol=symbol,
                        score=score,
                        direction=direction,
                        entry=entry,
                        stop_loss=stop_loss,
                        target=target,
                        rationale=rationale,
                    )
                    # send_email is synchronous — run in executor
                    success = await asyncio.to_thread(
                        send_email,
                        to_address=email_to,
                        subject=f"Trade Alert: {symbol} ({direction}, {score}/100)",
                        body=email_body,
                    )
                    message_log = email_body
                else:
                    logger.warning(
                        "Email channel %d (user %d) is missing email_to in config; skipping",
                        ch.id,
                        user_id,
                    )
            elif ch.channel_type == "webhook":
                webhook_url = config.get("webhook_url")
                signing_secret = config.get("signing_secret")
                if webhook_url and signing_secret:
                    signal_event = build_signal_event(
                        symbol=symbol,
                        score=score,
                        direction=direction,
                        entry=entry,
                        stop_loss=stop_loss,
                        target=target,
                        rationale=rationale,
                        sent_at=signal_time,
                    )
                    queued_delivery = await enqueue_signal_webhook(
                        user_id=user_id,
                        channel_id=int(ch.id),
                        pair=symbol,
                        direction=direction,
                        score=score,
                        payload=signal_event,
                        webhook_url=webhook_url,
                        signing_secret=signing_secret,
                    )
                    if queued_delivery is not None:
                        queued = True
                        message_log = json.dumps(
                            {
                                "delivery_id": queued_delivery.delivery_id,
                                "event": signal_event,
                                "status": "queued",
                            },
                            default=str,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    else:
                        message_log = json.dumps(
                            {"error": "queue_limit"},
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                else:
                    logger.warning(
                        "Webhook channel %d (user %d) is missing webhook_url or signing_secret; skipping",
                        ch.id,
                        user_id,
                    )
            else:
                logger.warning("Unknown channel type: %s", ch.channel_type)
                continue
        except Exception as exc:
            logger.exception(
                "Alert delivery failed unexpectedly for channel %d (user %d); continuing",
                ch.id,
                user_id,
            )
            message_log = json.dumps(
                {
                    "error": "channel_error",
                    "error_type": type(exc).__name__,
                },
                separators=(",", ":"),
                sort_keys=True,
            )

        if queued:
            channels_queued.append(ch.channel_type)
            continue

        # ── Log history ────────────────────────────────────────────
        alert_status = "sent" if success else "failed"
        log_entry = AlertHistory(
            user_id=user_id,
            pair=symbol,
            channel=ch.channel_type,
            score=score,
            direction=direction,
            message=message_log,
            status=alert_status,
        )
        session.add(log_entry)

        if success:
            channels_sent.append(ch.channel_type)

    if channels_sent:
        logger.info(
            "Alert sent for %s (score=%.1f) to user %d via %s",
            symbol,
            score,
            user_id,
            ", ".join(channels_sent),
        )

    return {
        "user_id": user_id,
        "pair": symbol,
        "score": score,
        "channels_sent": channels_sent,
        "channels_queued": channels_queued,
        "status": (
            "sent" if channels_sent else "queued" if channels_queued else "failed"
        ),
    }


async def _count_recent_alerts(
    session: AsyncSession,
    user_id: int,
    pair: str,
    cutoff: datetime,
) -> int:
    """Count sent or actively queued alerts for the pair during cooldown."""
    with session.no_autoflush:
        result = await session.execute(
            select(AlertHistory).where(
                AlertHistory.user_id == user_id,
                AlertHistory.pair == pair,
                AlertHistory.status == "sent",
                AlertHistory.created_at >= cutoff,
            )
        )
        active_result = await session.execute(
            select(SignalWebhookDelivery.id).where(
                SignalWebhookDelivery.user_id == user_id,
                SignalWebhookDelivery.pair == pair,
                SignalWebhookDelivery.status.in_(("pending", "processing")),
                SignalWebhookDelivery.created_at >= cutoff,
            )
        )
    return len(result.scalars().all()) + len(active_result.scalars().all())


# ── Small helpers ────────────────────────────────────────────────────────────


def _extract_float(data: Any, key: str) -> Optional[float]:
    """Extract a float value from a dict-like structure."""
    if not isinstance(data, dict):
        return None
    val = data.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_signal_time(value: Any) -> Optional[datetime]:
    """Parse a scan's stable timestamp for event identity when available."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
