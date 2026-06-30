"""Alert notification service — Telegram bot + Discord webhook + email integration.

Modules
-------
telegram : Telegram alert sender (polling-based, python-telegram-bot).
discord  : Discord webhook embed sender.
email    : SMTP email alert sender.
manager  : Orchestrator — threshold checks, dedup, channel routing, history,
           per-pair channel overrides (notification_channels).
"""
