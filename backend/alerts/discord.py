"""Discord webhook alert sender.

Sends rich embedded messages (Discord embed API) by POSTing JSON to
a user-configured webhook URL.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

WEBHOOK_URL_PREFIX = "https://discord.com/api/webhooks/"


def _validate_webhook_url(url: str) -> bool:
    """Return True if *url* looks like a genuine Discord webhook URL."""
    return url.startswith(WEBHOOK_URL_PREFIX)


# ── Public API ──────────────────────────────────────────────────────────────


def build_embed(
    symbol: str,
    score: float,
    direction: str,
    entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    target: Optional[float] = None,
    rationale: Optional[str] = None,
) -> dict[str, Any]:
    """Build a Discord embed dict (matching spec criterion A-01).

    Returns a dict that can be sent as the ``embeds`` array in a
    Discord webhook POST body.
    """
    fields: list[dict[str, Any]] = [
        {"name": "\U0001f3f7\ufe0f Symbol", "value": symbol, "inline": True},
        {"name": "\u2b50 Score", "value": f"{score}/100", "inline": True},
        {"name": "\U0001f4ca Direction", "value": direction, "inline": True},
    ]
    if entry is not None:
        fields.append({"name": "\U0001f4c5 Entry", "value": str(entry), "inline": True})
    if stop_loss is not None:
        fields.append({"name": "\U0001f6ab Stop Loss", "value": str(stop_loss), "inline": True})
    if target is not None:
        fields.append({"name": "\U0001f3af Target", "value": str(target), "inline": True})
    if rationale:
        fields.append({"name": "\U0001f4ac Rationale", "value": rationale, "inline": False})

    # Colour by direction: GREEN for LONG, RED for SHORT
    color = 0x00FF00 if direction.upper() == "LONG" else 0xFF0000

    return {
        "title": f"Trade Alert: {symbol}",
        "color": color,
        "fields": fields,
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }


async def send_webhook(webhook_url: str, embed: dict[str, Any]) -> bool:
    """POST a Discord embed to *webhook_url*.

    Returns ``True`` on success, ``False`` on failure.
    """
    if not _validate_webhook_url(webhook_url):
        logger.warning(
            "Invalid Discord webhook URL (must start with %s): %.80s",
            WEBHOOK_URL_PREFIX,
            webhook_url,
        )
        return False

    payload = {
        "embeds": [embed],
        "username": "Crypto Alert Bot",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.is_success:
                logger.info("Discord webhook sent (status=%d)", resp.status_code)
                return True
            else:
                logger.warning(
                    "Discord webhook returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
    except httpx.TimeoutException:
        logger.error("Discord webhook timed out")
        return False
    except Exception as exc:
        logger.error("Discord webhook failed: %s", exc)
        return False
