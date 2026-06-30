"""SMTP email alert sender.

Sends plain-text trade alerts via SMTP.  Configuration comes from environment
variables (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_FROM)
and per-channel config fields stored in the AlertChannel.config JSON.

Environment variables
---------------------
SMTP_HOST       SMTP server hostname (default "smtp.gmail.com")
SMTP_PORT       SMTP port (default 587)
SMTP_USERNAME   SMTP login username
SMTP_PASSWORD   SMTP login password / app password
EMAIL_FROM      From-address for outgoing alerts

Per-channel config (AlertChannel.config JSON)
-----------------------------------------------
email_to        Recipient email address (required)
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)

# ── Default SMTP config (from environment) ─────────────────────────────────

SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME: str = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM: str = os.environ.get("EMAIL_FROM", "")


# ── Public API ──────────────────────────────────────────────────────────────


def build_email_body(
    symbol: str,
    score: float,
    direction: str,
    entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    target: Optional[float] = None,
    rationale: Optional[str] = None,
) -> str:
    """Build a plain-text email body for a trade alert."""
    lines = [
        f"Trade Alert: {symbol}",
        f"{'=' * (len(symbol) + 14)}",
        "",
        f"  Symbol:     {symbol}",
        f"  Score:      {score}/100",
        f"  Direction:  {direction.upper()}",
    ]
    if entry is not None:
        lines.append(f"  Entry:      {entry}")
    if stop_loss is not None:
        lines.append(f"  Stop Loss:  {stop_loss}")
    if target is not None:
        lines.append(f"  Target:     {target}")
    if rationale:
        lines.append(f"  Rationale:  {rationale}")
    lines.append("")
    lines.append("-- Crypto Alert Bot")
    return "\n".join(lines)


def send_email(to_address: str, subject: str, body: str) -> bool:
    """Send a plain-text email via SMTP.

    Returns ``True`` on success, ``False`` on failure.
    Reads SMTP configuration from environment variables at call time
    (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_FROM).
    """
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USERNAME", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    email_from = os.environ.get("EMAIL_FROM", "")

    if not smtp_user or not smtp_pass:
        logger.error(
            "SMTP_USERNAME or SMTP_PASSWORD not set — email alerts disabled"
        )
        return False

    if not email_from:
        logger.error("EMAIL_FROM not set — email alerts disabled")
        return False

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = to_address

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15.0) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        logger.info("Email alert sent to %s", to_address)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed for %s", smtp_user)
        return False
    except smtplib.SMTPRecipientsRefused:
        logger.error("SMTP recipient refused: %s", to_address)
        return False
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("SMTP send failed: %s", exc)
        return False
