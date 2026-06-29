"""Alert notification service — Telegram bot + Discord webhook integration.

Modules
-------
telegram : Telegram alert sender (polling-based, python-telegram-bot).
discord  : Discord webhook embed sender.
manager  : Orchestrator — threshold checks, dedup, channel routing, history.
"""
