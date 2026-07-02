"""Async email sender using aiosmtplib + Jinja2 templates.

Sends HTML + plain-text emails via async SMTP.  All configuration comes from
environment variables, so missing config is a logged no-op (the alert path
never crashes).

Environment variables
---------------------
SMTP_HOST          SMTP server hostname (required for sending)
SMTP_PORT          SMTP port (default 587)
SMTP_USER          SMTP login username (required)
SMTP_PASSWORD       SMTP login password / app password (required)
SMTP_FROM          From-address for outgoing mail (default: SMTP_USER)
SMTP_USE_TLS       Whether to use STARTTLS ``true``/``false`` (default true)
SMTP_FROM_NAME     Display name for the From header (default "Miraj Alerts")
"""

from __future__ import annotations

import asyncio
import logging
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# ── Template directory ──────────────────────────────────────────────────────

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ── SMTP configuration ─────────────────────────────────────────────────────


def _smtp_config() -> dict[str, Any]:
    """Read SMTP configuration from environment variables at call time."""
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("SMTP_FROM", user)
    from_name = os.environ.get("SMTP_FROM_NAME", "Miraj Alerts")
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from_addr": from_addr,
        "from_name": from_name,
        "use_tls": use_tls,
    }


def is_configured() -> bool:
    """Return ``True`` if the minimum SMTP env vars are set."""
    cfg = _smtp_config()
    return bool(cfg["host"] and cfg["user"] and cfg["password"])


def _format_from(from_name: str, from_addr: str) -> str:
    """Build an RFC-5322 From header value."""
    if from_name and from_addr:
        return f"{from_name} <{from_addr}>"
    return from_addr


# ── Core send ───────────────────────────────────────────────────────────────


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None,
) -> bool:
    """Send an HTML email (with optional plain-text alternative) via async SMTP.

    Returns ``True`` on success, ``False`` on failure.  Missing SMTP config
    is treated as a no-op and returns ``False`` without raising.
    """
    cfg = _smtp_config()

    if not (cfg["host"] and cfg["user"] and cfg["password"]):
        logger.warning(
            "SMTP_HOST / SMTP_USER / SMTP_PASSWORD not configured — "
            "email to %s not sent (no-op)",
            to,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _format_from(cfg["from_name"], cfg["from_addr"])
    msg["To"] = to

    if text_body:
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
    else:
        msg.add_alternative(html_body, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg["host"],
            port=cfg["port"],
            username=cfg["user"],
            password=cfg["password"],
            start_tls=cfg["use_tls"],
            timeout=15.0,
        )
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


# ── Template rendering ──────────────────────────────────────────────────────


def render_template(template_name: str, **context: Any) -> str:
    """Render a Jinja2 email template to an HTML string."""
    template = _jinja_env.get_template(template_name)
    return template.render(**context)


# ── Price alert email ──────────────────────────────────────────────────────────


async def send_price_alert_email(
    to: str,
    symbol: str,
    direction: str,
    current_price: float,
    target_price: float,
    message: Optional[str] = None,
    dashboard_url: str = "https://ta.munafaplus.pk",
) -> bool:
    """Render the price-alert template and send the email.

    Parameters
    ----------
    to
        Recipient email address.
    symbol
        Trading symbol, e.g. ``"BTCUSDT"``.
    direction
        ``"above"`` or ``"below"``.
    current_price
        The current market price at trigger time.
    target_price
        The alert's target/stop price level.
    message
        Optional user-defined note attached to the alert.
    dashboard_url
        Base URL for the analysis link. Defaults to the production host.
    """
    analysis_url = f"{dashboard_url.rstrip('/')}/analysis/{symbol.upper()}"

    html_body = render_template(
        "price_alert.html",
        symbol=symbol.upper(),
        direction=direction.lower(),
        current_price=current_price,
        target_price=target_price,
        message=message,
        dashboard_url=dashboard_url,
        analysis_url=analysis_url,
    )

    subject = (
        f"Miraj Alert: {symbol.upper()} crossed "
        f"{direction} {target_price}"
    )

    return await send_email(to, subject, html_body)


async def send_test_email(to: str) -> bool:
    """Send a concise plain test email — used by the /settings/email/test route."""
    html_body = render_template(
        "price_alert.html",
        symbol="TEST",
        direction="test",
        current_price=0.0,
        target_price=0.0,
        message="This is a test email from Miraj Dashboard. "
        "If you received this, email alerts are configured correctly.",
        dashboard_url="https://ta.munafaplus.pk",
        analysis_url="https://ta.munafaplus.pk",
    )
    subject = "Miraj Dashboard — Test Email"
    return await send_email(to, subject, html_body)
