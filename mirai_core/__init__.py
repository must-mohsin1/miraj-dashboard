"""
mirai_core — Crypto technical analysis engine.

Refactored from the crypto-pair-analysis skill.  Provides importable modules
for macro data, OHLCV fetching, indicators, QQE Mod, SMC, patterns,
confluence scoring, trade planning, and chart rendering.
"""

from mirai_core import config
from mirai_core import macro
from mirai_core import ohlcv
from mirai_core import indicators
from mirai_core import qqe_mod
from mirai_core import smc
from mirai_core import patterns
from mirai_core import confluence
from mirai_core import trade_plan
from mirai_core import charts
from mirai_core import verdict

__all__ = [
    "config",
    "macro",
    "ohlcv",
    "indicators",
    "qqe_mod",
    "smc",
    "patterns",
    "confluence",
    "trade_plan",
    "charts",
    "verdict",
]

__version__ = "1.0.0"
