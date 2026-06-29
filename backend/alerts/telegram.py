"""Telegram alert sender.

Uses *python-telegram-bot* with polling (no webhook for MVP).
Requires ``TELEGRAM_BOT_TOKEN`` environment variable.

An ``Application`` singleton is lazily created with a polling-based
``Updater`` so that scheduled scans can call ``send_alert`` without
managing the bot lifecycle themselves.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)

# ── Lazy singleton ──────────────────────────────────────────────────────────
_application: Optional["Application"] = None


def _get_bot_token() -> str:
    """Return the Telegram bot token from the environment."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set — Telegram alerts disabled"
        )
    return token


def get_application() -> "Application":
    """Return or create the polling-based ``Application`` singleton."""
    global _application
    if _application is not None:
        return _application

    from telegram import Bot
    from telegram.ext import ApplicationBuilder

    token = _get_bot_token()
    _application = (
        ApplicationBuilder()
        .token(token)
        .build()
    )
    logger.info("Telegram Application initialised (polling)")
    return _application


# ── Public API ──────────────────────────────────────────────────────────────


def format_alert_message(
    symbol: str,
    score: float,
    direction: str,
    entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    target: Optional[float] = None,
    rationale: Optional[str] = None,
) -> str:
    """Build a human-readable alert message string.

    Matches spec criterion A-01:
      - Symbol tag       🏷️
      - Confluence score ⭐
      - Trade direction  📊
      - Key levels: entry / stop / target
    """
    lines = [
        f"\U0001f3f7\ufe0f *{symbol}*",
        f"\u2b50 Score: {score}/100",
        f"\U0001f4ca Direction: *{direction}*",
    ]
    if entry is not None:
        lines.append(f"\U0001f4c5 Entry: {entry}")
    if stop_loss is not None:
        lines.append(f"\U0001f6ab Stop Loss: {stop_loss}")
    if target is not None:
        lines.append(f"\U0001f3af Target: {target}")
    if rationale:
        lines.append(f"\U0001f4ac {rationale}")

    return "\n".join(lines)


async def send_alert(chat_id: str, text: str) -> bool:
    """Send a Telegram message to *chat_id*.

    Returns ``True`` on success, ``False`` on failure.
    The bot is lazily initialised via the polling ``Application``.
    """
    try:
        app = get_application()
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        logger.info("Telegram alert sent to %s", chat_id)
        return True
    except Exception as exc:
        logger.error("Telegram send failed to %s: %s", chat_id, exc)
        return False


async def start_polling() -> None:
    """Start the Telegram polling loop.

    Call once during application startup.  Safe to call multiple times
    (the library guards against double-start).
    """
    app = get_application()
    if not app.updater or not app.updater.running:
        await app.initialize()
        await app.updater.start_polling()  # type: ignore[union-attr]
        logger.info("Telegram polling started")
    else:
        logger.info("Telegram polling already running")


async def stop_polling() -> None:
    """Gracefully stop the polling loop."""
    global _application
    if _application is not None:
        try:
            if _application.updater and _application.updater.running:
                await _application.updater.stop()
                logger.info("Telegram polling stopped")
        except Exception as exc:
            logger.warning("Error stopping Telegram polling: %s", exc)
        finally:
            _application = None
