"""Price alert service — create/check/trigger price alerts.

Responsibilities
----------------
1. **Create** — persist a new PriceAlert row with active status.
2. **Check** — evaluate all active alerts against current market prices.
3. **Trigger** — when price hits the alert level, mark as triggered and
   send notification via the user's enabled alert channels (Telegram/Discord).

Usage::

    from backend.services.price_alert_service import check_price_alerts

    outcomes = await check_price_alerts(session)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AlertChannel, PriceAlert, User
from backend.alerts.telegram import format_alert_message as format_tg_message, send_alert
from backend.alerts.discord import build_embed, send_webhook

logger = logging.getLogger(__name__)


# ── Public API ──────────────────────────────────────────────────────────────


async def create_price_alert(
    session: AsyncSession,
    user_id: int,
    symbol: str,
    price_level: float,
    direction: str,
    alert_type: str = "price",
    message: Optional[str] = None,
) -> PriceAlert:
    """Create a new active price alert for *symbol*.

    *direction* must be ``"above"`` (trigger when price goes above the level)
    or ``"below"`` (trigger when price goes below the level).

    Returns the persisted ``PriceAlert`` row.
    """
    alert = PriceAlert(
        user_id=user_id,
        symbol=symbol.strip().upper(),
        alert_type=alert_type,
        direction=direction,
        price_level=price_level,
        message=message,
        status="active",
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    logger.info(
        "Price alert created: id=%d user=%d symbol=%s level=%s %s",
        alert.id, user_id, alert.symbol, price_level, direction,
    )
    return alert


async def cancel_price_alert(
    session: AsyncSession,
    alert_id: int,
    user_id: int,
) -> Optional[PriceAlert]:
    """Cancel an active price alert (set status to ``cancelled``).

    Returns the updated ``PriceAlert`` or ``None`` if not found or not owned
    by *user_id*.
    """
    result = await session.execute(
        select(PriceAlert).where(
            PriceAlert.id == alert_id,
            PriceAlert.user_id == user_id,
        )
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        return None
    alert.status = "cancelled"
    alert.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(alert)
    logger.info("Price alert cancelled: id=%d", alert.id)
    return alert


async def get_price_alert(
    session: AsyncSession,
    alert_id: int,
    user_id: int,
) -> Optional[PriceAlert]:
    """Fetch a single price alert by id, scoped to *user_id*."""
    result = await session.execute(
        select(PriceAlert).where(
            PriceAlert.id == alert_id,
            PriceAlert.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_price_alerts(
    session: AsyncSession,
    user_id: int,
    status: Optional[str] = None,
) -> list[PriceAlert]:
    """List price alerts for *user_id*, optionally filtered by *status*."""
    query = select(PriceAlert).where(PriceAlert.user_id == user_id)
    if status:
        query = query.where(PriceAlert.status == status)
    query = query.order_by(PriceAlert.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def delete_price_alert(
    session: AsyncSession,
    alert_id: int,
    user_id: int,
) -> bool:
    """Permanently delete a price alert.

    Returns ``True`` if deleted, ``False`` if not found or not owned.
    """
    result = await session.execute(
        select(PriceAlert).where(
            PriceAlert.id == alert_id,
            PriceAlert.user_id == user_id,
        )
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        return False
    await session.delete(alert)
    await session.commit()
    logger.info("Price alert deleted: id=%d", alert.id)
    return True


# ── Price checking ─────────────────────────────────────────────────────────


async def check_single_price(
    symbol: str,
) -> Optional[float]:
    """Fetch the latest price for *symbol* via yfinance.

    Returns the current price as a float, or ``None`` if the fetch fails.
    """
    import yfinance as yf
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if data is None or data.empty:
            # Fall back to 5d daily
            data = ticker.history(period="5d", interval="1d")
        if data is not None and not data.empty:
            return float(data["Close"].iloc[-1])
        return None
    except Exception as exc:
        logger.warning("Failed to fetch price for %s: %s", symbol, exc)
        return None


async def check_price_alerts(session: AsyncSession) -> list[dict[str, Any]]:
    """Check all active price alerts and trigger those whose level is hit.

    For each active alert:
      1. Fetch the current market price via yfinance.
      2. Evaluate if the trigger condition (above/below) is met.
      3. If met, mark as triggered and send notifications.

    Returns a list of outcome dicts for logging::

        [
          {"alert_id": 1, "symbol": "BTC-USD", "status": "triggered", "price": 65432.1},
          ...
        ]
    """
    # Fetch all active price alerts
    result = await session.execute(
        select(PriceAlert).where(PriceAlert.status == "active")
    )
    alerts = list(result.scalars().all())

    if not alerts:
        logger.debug("No active price alerts to check")
        return []

    # Group alerts by symbol to avoid redundant price fetches
    from collections import defaultdict

    by_symbol: dict[str, list[PriceAlert]] = defaultdict(list)
    for alert in alerts:
        by_symbol[alert.symbol].append(alert)

    outcomes: list[dict[str, Any]] = []

    for symbol, symbol_alerts in by_symbol.items():
        current_price = await check_single_price(symbol)
        if current_price is None:
            logger.warning("Skipping price alerts for %s (price unavailable)", symbol)
            continue

        for alert in symbol_alerts:
            triggered = False
            if alert.direction == "above" and current_price >= alert.price_level:
                triggered = True
            elif alert.direction == "below" and current_price <= alert.price_level:
                triggered = True

            if triggered:
                outcome = await _trigger_alert(session, alert, current_price)
                outcomes.append(outcome)

    return outcomes


# ── Trigger handler ────────────────────────────────────────────────────────


async def _trigger_alert(
    session: AsyncSession,
    alert: PriceAlert,
    current_price: float,
) -> dict[str, Any]:
    """Mark *alert* as triggered and send notifications.

    Returns an outcome dict.
    """
    alert.status = "triggered"
    alert.current_price = current_price
    alert.triggered_at = datetime.now(timezone.utc)
    alert.updated_at = datetime.now(timezone.utc)

    # Send via user's enabled alert channels
    channels_result = await session.execute(
        select(AlertChannel).where(
            AlertChannel.user_id == alert.user_id,
            AlertChannel.enabled == 1,
        )
    )
    channels = list(channels_result.scalars().all())

    channels_sent: list[str] = []
    direction_label = "above" if alert.direction == "above" else "below"
    direction_arrow = "↗" if alert.direction == "above" else "↘"

    # Format message (reuse existing formatters with a dedicated prefix)
    tg_text = _format_price_alert_message(
        alert, current_price, direction_label, direction_arrow,
    )
    dc_embed = _build_price_alert_embed(
        alert, current_price, direction_label, direction_arrow,
    )

    for ch in channels:
        try:
            config = json.loads(ch.config) if ch.config else {}
        except (json.JSONDecodeError, TypeError):
            config = {}

        success = False
        if ch.channel_type == "telegram":
            chat_id = config.get("chat_id")
            if chat_id:
                success = await send_alert(str(chat_id), tg_text)
        elif ch.channel_type == "discord":
            webhook_url = config.get("webhook_url")
            if webhook_url:
                success = await send_webhook(str(webhook_url), dc_embed)

        if success:
            channels_sent.append(ch.channel_type)

    await session.commit()

    outcome: dict[str, Any] = {
        "alert_id": alert.id,
        "symbol": alert.symbol,
        "price_level": alert.price_level,
        "current_price": current_price,
        "status": "triggered",
        "channels_sent": channels_sent,
    }
    logger.info(
        "Price alert %d triggered: %s %s %.2f (current=%.2f) via %s",
        alert.id, alert.symbol, direction_label, alert.price_level,
        current_price, ", ".join(channels_sent) if channels_sent else "none",
    )
    return outcome


# ── Message formatters ─────────────────────────────────────────────────────


def _format_price_alert_message(
    alert: PriceAlert,
    current_price: float,
    direction_label: str,
    direction_arrow: str,
) -> str:
    """Build a Telegram-formatted price alert message."""
    lines = [
        f"🔔 *Price Alert Triggered*",
        f"🏷️ *{alert.symbol}*",
        f"📊 Level: `{alert.price_level}` {direction_arrow}",
        f"💵 Current: `{current_price}`",
        f"📐 Direction: *{direction_label.upper()}*",
    ]
    if alert.message:
        lines.append(f"💬 {alert.message}")
    return "\n".join(lines)


def _build_price_alert_embed(
    alert: PriceAlert,
    current_price: float,
    direction_label: str,
    direction_arrow: str,
) -> dict[str, Any]:
    """Build a Discord embed for a triggered price alert."""
    from datetime import datetime as dt_mod

    fields = [
        {"name": "🏷️ Symbol", "value": alert.symbol, "inline": True},
        {"name": "📊 Level", "value": f"{alert.price_level}", "inline": True},
        {"name": "💵 Current Price", "value": f"{current_price}", "inline": True},
        {"name": "📐 Direction", "value": direction_label.upper(), "inline": True},
    ]
    if alert.message:
        fields.append({"name": "💬 Note", "value": alert.message, "inline": False})

    # Green for above, Red for below
    color = 0x00FF00 if alert.direction == "above" else 0xFF0000

    return {
        "title": f"🔔 Price Alert: {alert.symbol}",
        "color": color,
        "fields": fields,
        "timestamp": dt_mod.utcnow().isoformat() + "Z",
    }
