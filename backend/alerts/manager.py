"""Alert manager — orchestrator for trade alert dispatch.

Responsibilities
----------------
1. **Threshold filtering** — only send alerts when ``confluence_score >=``
   the user's per-pair threshold (from ``PairSetting.settings``).
2. **Dedup** — skip symbols already alerted within the cooldown period
   (configurable per-channel via ``ALERT_COOLDOWN_HOURS``, default 4h).
3. **Channel routing** — iterate over the user's enabled ``AlertChannel``
   rows and deliver via Telegram or Discord.
4. **History logging** — persist every send attempt to ``AlertHistory``.

Typical usage (inside the scheduled scan)::

    from backend.alerts.manager import process_scan_results

    await process_scan_results(session, scan_results_by_user)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AlertChannel, AlertHistory, PairSetting, User
from backend.alerts.email import build_email_body, send_email
from backend.alerts.telegram import format_alert_message, send_alert
from backend.alerts.discord import build_embed, send_webhook

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

        for scan_result in results:
            outcome = await _process_single_result(
                session, user_id, scan_result, channels, pair_settings_map,
            )
            if outcome:
                outcomes.append(outcome)

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
    session: AsyncSession, user_id: int,
) -> list[AlertChannel]:
    """Return all enabled AlertChannel rows for *user_id*."""
    result = await session.execute(
        select(AlertChannel).where(
            AlertChannel.user_id == user_id,
            AlertChannel.enabled == 1,
        )
    )
    return list(result.scalars().all())


async def _get_pair_settings_map(
    session: AsyncSession, user_id: int,
) -> dict[str, dict[str, Any]]:
    """Return a dict of ``pair → full settings dict`` from PairSetting rows.

    Returns the parsed JSON ``settings`` dict for every pair that has one.
    Callers access ``alert_threshold`` and ``alert_enabled`` from the value::

        info = settings_map.get(symbol, {})
        threshold = info.get("alert_threshold") or DEFAULT_THRESHOLD
        enabled = info.get("alert_enabled", True)
    """
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
    symbol = (scan_result.get("symbol") or "").strip().upper()
    if not symbol:
        logger.warning("Scan result missing symbol; skipping")
        return None

    # A confluence score alone is only a watch condition.  Manual-entry
    # notifications require an explicit confirmation from the trade plan.
    trade_plan = scan_result.get("trade_plan", {}) or {}
    if not is_actionable_trade_plan(trade_plan):
        logger.debug("Symbol %s has no confirmed trade decision; no alert", symbol)
        return None

    score = scan_result.get("confluence_score") or scan_result.get("overall_score") or 0.0
    score = float(score)

    # ── Fetch pair-specific settings ──────────────────────────────────
    pair_settings = pair_settings_map.get(symbol, {})

    # ── Check alert_enabled ───────────────────────────────────────────
    # Use truthiness check (not identity 'is False') so that any falsy
    # value (False, 0, None, "") correctly disables alerts.
    if not pair_settings.get("alert_enabled", True):
        logger.debug(
            "Alert disabled for %s (user %d) via pair settings",
            symbol, user_id,
        )
        return None

    # ── Threshold check ─────────────────────────────────────────────
    threshold = float(pair_settings.get("alert_threshold") or DEFAULT_THRESHOLD)
    if score < threshold:
        logger.debug(
            "Symbol %s score %.1f < threshold %.1f for user %d; no alert",
            symbol, score, threshold, user_id,
        )
        return None

    # ── Extract trade plan details ──────────────────────────────────
    trade_plan = scan_result.get("trade_plan", {}) or {}
    direction = (trade_plan.get("direction") or "LONG").upper() if isinstance(trade_plan, dict) else "LONG"
    entry = _extract_float(trade_plan, "entry")
    stop_loss = _extract_float(trade_plan, "stop_loss")
    target = _extract_float(trade_plan, "target_1") or _extract_float(trade_plan, "target")
    rationale = (
        trade_plan.get("reasoning")
        or trade_plan.get("rationale")
        or trade_plan.get("verdict")
    )
    if isinstance(rationale, str):
        rationale = rationale[:200]  # keep it short

    # ── Build messages ──────────────────────────────────────────────
    tg_text = format_alert_message(
        symbol=symbol, score=score, direction=direction,
        entry=entry, stop_loss=stop_loss, target=target, rationale=rationale,
    )
    dc_embed = build_embed(
        symbol=symbol, score=score, direction=direction,
        entry=entry, stop_loss=stop_loss, target=target, rationale=rationale,
    )

    # ── Cooldown check (per symbol, per user) ───────────────────────
    cooldown_hours = DEFAULT_COOLDOWN_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)

    recent_count = await _count_recent_alerts(session, user_id, symbol, cutoff)
    if recent_count > 0:
        logger.info(
            "Symbol %s for user %d was alerted %d time(s) in last %dh; skipping",
            symbol, user_id, recent_count, cooldown_hours,
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
                "falling back to all channels",
                symbol, user_id, notification_channels,
            )
        else:
            channels = filtered

    # ── Deliver to each enabled channel ─────────────────────────────
    channels_sent: list[str] = []
    for ch in channels:
        try:
            config = json.loads(ch.config) if ch.config else {}
        except (json.JSONDecodeError, TypeError):
            config = {}

        success = False
        message_log = ""
        if ch.channel_type == "telegram":
            chat_id = config.get("chat_id")
            if chat_id:
                success = await send_alert(str(chat_id), tg_text)
                message_log = tg_text
            else:
                logger.warning(
                    "Telegram channel %d (user %d) is missing chat_id in config; skipping",
                    ch.id, user_id,
                )
        elif ch.channel_type == "discord":
            webhook_url = config.get("webhook_url")
            if webhook_url:
                success = await send_webhook(str(webhook_url), dc_embed)
                message_log = str(dc_embed)
            else:
                logger.warning(
                    "Discord channel %d (user %d) is missing webhook_url in config; skipping",
                    ch.id, user_id,
                )
        elif ch.channel_type == "email":
            email_to = config.get("email_to")
            if email_to:
                email_body = build_email_body(
                    symbol=symbol, score=score, direction=direction,
                    entry=entry, stop_loss=stop_loss, target=target,
                    rationale=rationale,
                )
                # send_email is synchronous — run in executor
                success = await asyncio.to_thread(
                    send_email,
                    to_address=email_to,
                    subject=f"Trade Alert: {symbol} ({direction.upper()}, {score}/100)",
                    body=email_body,
                )
                message_log = email_body
            else:
                logger.warning(
                    "Email channel %d (user %d) is missing email_to in config; skipping",
                    ch.id, user_id,
                )
        else:
            logger.warning("Unknown channel type: %s", ch.channel_type)
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
            symbol, score, user_id, ", ".join(channels_sent),
        )

    return {
        "user_id": user_id,
        "pair": symbol,
        "score": score,
        "channels_sent": channels_sent,
        "status": "sent" if channels_sent else "failed",
    }


async def _count_recent_alerts(
    session: AsyncSession,
    user_id: int,
    pair: str,
    cutoff: datetime,
) -> int:
    """Count how many alerts were sent for *pair* to *user_id* after *cutoff*."""
    result = await session.execute(
        select(AlertHistory)
        .where(
            AlertHistory.user_id == user_id,
            AlertHistory.pair == pair,
            AlertHistory.status == "sent",
            AlertHistory.created_at >= cutoff,
        )
    )
    return len(result.scalars().all())


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
