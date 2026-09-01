"""Alert notification service — Telegram, email, and signed webhooks.

Modules
-------
telegram : Telegram alert sender (polling-based, python-telegram-bot).
email    : SMTP email alert sender.
webhook  : HMAC-signed generic automation webhook sender.
webhook_outbox : Durable leased queue and retry dispatcher for signal webhooks.
manager  : Orchestrator — threshold checks, dedup, channel routing, history,
           per-pair channel overrides (notification_channels).
"""

# Discord webhooks produced stale, unusable signal noise. Existing Discord
# AlertChannel rows may remain in the database so users can delete them, but
# no new Discord channels are accepted and no delivery path may send to them.
RETIRED_ALERT_CHANNEL_TYPES = frozenset({"discord"})
