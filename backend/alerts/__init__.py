"""Alert notification service — Telegram, Discord, email, and signed webhooks.

Modules
-------
telegram : Telegram alert sender (polling-based, python-telegram-bot).
discord  : Discord webhook embed sender.
email    : SMTP email alert sender.
webhook  : HMAC-signed generic automation webhook sender.
webhook_outbox : Durable leased queue and retry dispatcher for signal webhooks.
manager  : Orchestrator — threshold checks, dedup, channel routing, history,
           per-pair channel overrides (notification_channels).
"""
