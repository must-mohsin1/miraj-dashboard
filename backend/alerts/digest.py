"""Daily digest service — Telegram summary of all scanned pairs.

Queries today's analyses for all users, builds a formatted markdown message,
and sends it via a Telegram bot.  Designed to run as an APScheduler cron job.

Configuration via environment variables
----------------------------------------
TELEGRAM_BOT_TOKEN    Telegram bot token (optional — when unset, runs in log-only mode)
TELEGRAM_CHAT_ID      Target chat/group ID for the digest message
DIGEST_HOUR           Hour for daily digest (default 20, 24-hour UTC)
DIGEST_MINUTE         Minute for daily digest (default 0)

Acceptance criteria
--------------------
- Daily cron job runs at configurable time (default 20:00 UTC)
- Digest message lists all pairs scanned that day
- Each pair entry: symbol, confluence_score, trade direction, highest timeframe confirming
- Summary line: total pairs, high-confluence count (>=10), actionable setups count
- Digest sent via Telegram bot to configured chat_id
- No duplicate digest sent if scan already produced alert for same setup
- Empty day: sends "No scans run today" message
- Digest format: clean, readable markdown
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import select

from backend.database import get_session_factory
from backend.models import Analysis

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "20"))
DIGEST_MINUTE = int(os.environ.get("DIGEST_MINUTE", "0"))
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

# Telegram API base URL
_TG_API_BASE = "https://api.telegram.org/bot"

# Characters that must be escaped in MarkdownV2 (Telegram Bot API).
_MARKDOWNV2_SPECIAL = set('_*[]()~`>#+-=|{}.!')


def _escape_markdown_v2(text: str) -> str:
    """Escape all MarkdownV2 special characters in *text*.

    Escapes: ``_ * [ ] ( ) ~ ` > # + - = | { } . !``

    Safe to use both inside and outside code spans — an escaped non-special
    character (e.g. ``\.``) renders as the literal character itself.
    """
    return "".join(f"\\{ch}" if ch in _MARKDOWNV2_SPECIAL else ch for ch in text)


# ── Timeframe hierarchy helper ────────────────────────────────────────────────


def _extract_highest_tf(score_breakdown: Optional[dict[str, Any]]) -> Optional[str]:
    """Return the highest timeframe that confirms from the score breakdown.

    Checks regime breakdown (weekly_structure, daily_structure) and confirmation
    breakdown (h4_structure, m15_structure).  Returns ``None`` when no timeframe
    confirms.

    Timeframe hierarchy (highest to lowest): WEEKLY → DAILY → 4H → 15M
    """
    if not score_breakdown or not isinstance(score_breakdown, dict):
        return None

    regime = score_breakdown.get("regime", {})
    regime_bd = regime.get("breakdown", {}) if isinstance(regime, dict) else {}

    confirmation = score_breakdown.get("confirmation", {})
    conf_bd = confirmation.get("breakdown", {}) if isinstance(confirmation, dict) else {}

    # Check from highest to lowest
    if regime_bd.get("weekly_structure"):
        return "WEEKLY"
    if regime_bd.get("daily_structure"):
        return "DAILY"
    if conf_bd.get("h4_structure"):
        return "4H"
    if conf_bd.get("m15_structure"):
        return "15M"

    return None


# ── Message builder ───────────────────────────────────────────────────────────


def build_digest_message(rows: list[dict[str, Any]]) -> str:
    """Build a formatted markdown digest message from analysis rows.

    *rows* is a list of dicts with keys:
        symbol, confluence_score, direction, highest_tf, actionable,
        score_breakdown (optional, for future use).

    Returns ``"No scans run today"`` when *rows* is empty.

    Note: dynamic values are MarkdownV2-escaped so that special characters
    in symbol names / scores / directions don't break formatting, while
    the intentional ``*bold*`` and `` `code` `` markers are preserved.
    """
    if not rows:
        return "\U0001f4ed *Daily Digest* \u2014 No scans run today."

    lines: list[str] = []
    lines.append("\U0001f4ca *Daily Market Digest*")
    lines.append("")

    timestamp = _escape_markdown_v2(
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )
    lines.append(f"`{timestamp}`")
    lines.append("")

    # Sort by confluence_score descending
    sorted_rows = sorted(rows, key=lambda r: r.get("confluence_score", 0.0), reverse=True)

    for row in sorted_rows:
        symbol = _escape_markdown_v2(str(row.get("symbol", "???")))
        score = row.get("confluence_score", 0.0)
        direction = row.get("direction", "\u2014")
        highest_tf = _escape_markdown_v2(str(row.get("highest_tf", "\u2014")))
        actionable = row.get("actionable", False)

        # Emoji based on confidence
        if score >= 10:
            confidence_icon = "\U0001f7e2"
        elif score >= 5:
            confidence_icon = "\U0001f7e1"
        else:
            confidence_icon = "\U0001f534"

        # Direction arrow
        if direction and direction.upper() == "LONG":
            dir_arrow = "\U0001f7e2 LONG \u2191"
        elif direction and direction.upper() == "SHORT":
            dir_arrow = "\U0001f534 SHORT \u2193"
        else:
            dir_arrow = "\u2014"

        actionable_tag = " \u26a1\ufe0fACTIONABLE" if actionable else ""

        lines.append(
            f"{confidence_icon} *{symbol}*{actionable_tag}\n"
            f"   Score: `{_escape_markdown_v2(str(score))}`"
            f" \u00b7 Direction: {dir_arrow}"
            f" \u00b7 TF: `{highest_tf}`"
        )
        lines.append("")

    # ── Summary line ───────────────────────────────────────────────────
    total = len(rows)
    high_confluence = sum(1 for r in rows if r.get("confluence_score", 0.0) >= 10)
    actionable_count = sum(1 for r in rows if r.get("actionable", False))

    lines.append("\u2014\u2014\u2014")
    lines.append(
        f"*Summary:* {total} pairs \u00b7 "
        f"High-confluence (\u226510): {high_confluence} \u00b7 "
        f"Actionable setups: {actionable_count}"
    )

    return "\n".join(lines)


# ── Telegram client ───────────────────────────────────────────────────────────


class TelegramClient:
    """Simple async Telegram Bot API client.

    Creates one ``httpx.AsyncClient`` per ``send_message`` call (short-lived,
    appropriate for daily scheduled jobs).  Disabled when *bot_token* is empty.

    The *text* passed to ``send_message`` is expected to be pre-escaped for
    MarkdownV2 — the method does NOT apply additional escaping so that
    intentional formatting markers (``*bold*``, `` `code` ``) are preserved.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = bool(self.bot_token and self.chat_id)

    async def send_message(self, text: str) -> bool:
        """Send *text* to the configured chat via Telegram Bot API.

        Uses ``MarkdownV2`` parse mode.  *text* is assumed to be pre-escaped
        — the method does NOT apply additional escaping (callers use
        ``_escape_markdown_v2()`` on dynamic values before building the
        message).  Returns ``True`` on success, ``False`` on any failure
        (HTTP error, network error, disabled).
        """
        if not self.enabled:
            logger.info("Telegram disabled: no bot token or chat id configured")
            return False

        url = f"{_TG_API_BASE}{self.bot_token}/sendMessage"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "MarkdownV2",
                        "disable_web_page_preview": True,
                    },
                )
                if response.status_code == 200:
                    logger.info("Telegram digest sent successfully to chat %s", self.chat_id)
                    return True
                else:
                    logger.error(
                        "Telegram send failed (HTTP %d): %s",
                        response.status_code,
                        response.text,
                    )
                    return False
        except Exception as exc:
            logger.error("Telegram send error: %s", exc)
            return False


# ── Global client singleton ────────────────────────────────────────────────────

_client: Optional[TelegramClient] = None


def _get_telegram_client() -> TelegramClient:
    """Return the singleton TelegramClient (re-initialised on re-import).

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from module-level config,
    which in turn reads from env vars at import time.
    """
    global _client
    if _client is None:
        _client = TelegramClient(bot_token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)
    return _client


# ── Row builder ───────────────────────────────────────────────────────────────


def _parse_analysis_to_row(analysis: Analysis) -> Optional[dict[str, Any]]:
    """Parse a single Analysis row into a digest row dict.

    Extracts the chat-friendly fields from the JSON ``result`` column.
    Returns ``None`` when the result cannot be parsed or is missing.
    """
    if not analysis.result:
        return None

    try:
        result = json.loads(analysis.result)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Cannot parse result JSON for analysis %d", analysis.id)
        return None

    if not isinstance(result, dict):
        return None

    score = result.get("confluence_score")
    if score is None:
        score = analysis.score or 0.0

    trade_plan = result.get("trade_plan", {}) or {}
    direction_raw = trade_plan.get("direction", "")
    direction = direction_raw.strip().upper() if isinstance(direction_raw, str) else "—"

    trade_decision = trade_plan.get("trade_decision", False)
    actionable = bool(trade_decision)

    score_breakdown = result.get("score_breakdown", {})
    highest_tf = _extract_highest_tf(score_breakdown)

    return {
        "symbol": analysis.pair,
        "confluence_score": float(score) if score is not None else 0.0,
        "direction": direction if direction else "—",
        "highest_tf": highest_tf or "—",
        "actionable": actionable,
        "score_breakdown": score_breakdown,
    }


# ── Scheduler callback ────────────────────────────────────────────────────────


async def send_daily_digest() -> None:
    """APScheduler job callback — query today's analyses and send digest.

    Flow:
      1. Query all Analysis rows created today (UTC).
      2. Group by user_id.
      3. For each user with analyses, parse results into digest rows.
      4. Build markdown message per user.
      5. Send via TelegramBot.

    When there are no analyses for a user, sends "No scans run today".
    """
    logger.info("Daily digest: starting")

    factory = get_session_factory()
    async with factory() as session:
        # ── Calculate today's start (UTC) ──────────────────────────────
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # ── Query today's analyses, grouped by user ────────────────────
        stmt = (
            select(Analysis)
            .where(Analysis.created_at >= today_start)
            .order_by(Analysis.user_id, Analysis.created_at.desc())
        )
        result = await session.execute(stmt)
        analyses = result.scalars().all()

        if not analyses:
            logger.info("Daily digest: no analyses found for today")
            # Still send an empty digest notification
            client = _get_telegram_client()
            msg = build_digest_message([])
            await client.send_message(msg)
            return

        # ── Group by user_id ───────────────────────────────────────────
        user_analyses: dict[int, list[Analysis]] = {}
        for a in analyses:
            user_analyses.setdefault(a.user_id, []).append(a)

        client = _get_telegram_client()

        for user_id, user_rows_raw in user_analyses.items():
            # Parse each analysis into a digest row (deduplicate by symbol — take latest)
            seen_symbols: set[str] = set()
            rows: list[dict[str, Any]] = []
            for a in user_rows_raw:
                if a.pair in seen_symbols:
                    continue
                seen_symbols.add(a.pair)
                row = _parse_analysis_to_row(a)
                if row is not None:
                    rows.append(row)

            if not rows:
                msg = build_digest_message([])
            else:
                msg = build_digest_message(rows)

            await client.send_message(msg)

        logger.info("Daily digest: sent to %d user(s)", len(user_analyses))


# ── Scheduler registration ────────────────────────────────────────────────────


def register_digest_job(scheduler) -> None:
    """Register the daily digest cron job on *scheduler*.

    Uses ``DIGEST_HOUR`` and ``DIGEST_MINUTE`` from env vars (default 20:00 UTC).
    Idempotent — replaces any existing job with id ``daily_digest``.
    """
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        send_daily_digest,
        trigger=CronTrigger(hour=str(DIGEST_HOUR), minute=str(DIGEST_MINUTE)),
        id="daily_digest",
        name=f"Daily digest ({DIGEST_HOUR:02d}:{DIGEST_MINUTE:02d} UTC)",
        replace_existing=True,
    )
    logger.info(
        "Daily digest registered: %02d:%02d UTC",
        DIGEST_HOUR,
        DIGEST_MINUTE,
    )
