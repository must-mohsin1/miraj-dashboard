"""Deterministic redacted closed-position fixture for Portfolio Intelligence tests.

This synthetic fixture pins the audit contract without depending on live MEXC
state. Values are redacted, stable, and intentionally small; ``pnl`` mirrors
MEXC's reported ``closeProfitLoss`` field and ``pnl_percent`` mirrors
``profitRatio`` as a per-position ROI percentage.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_BASE_CLOSE = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

# 48 wins of $1.05 plus one loss of -$1.17 = frozen reported total $49.23.
_FROZEN_REPORTED_PNLS = [1.05] * 48 + [-1.17]
_FROZEN_ROI_PCTS = [2.1] * 12 + [1.7] * 12 + [0.9] * 12 + [0.3] * 12 + [-4.8]
_FROZEN_SYMBOLS = ["BTC_USDT", "ETH_USDT", "SNDK_USDT", "SOL_USDT", "DOGE_USDT", "ADA_USDT", "POL_USDT"]

FROZEN_POSITIONS: list[dict[str, Any]] = [
    {
        "symbol": _FROZEN_SYMBOLS[i % len(_FROZEN_SYMBOLS)],
        "side": "long" if i % 3 else "short",
        "size": round(0.25 + (i % 5) * 0.1, 4),
        "entry_price": round(100 + i * 0.25, 4),
        "exit_price": round(100 + i * 0.25 + (0.42 if pnl >= 0 else -0.42), 4),
        "closeProfitLoss": pnl,
        "profitRatio": _FROZEN_ROI_PCTS[i],
        "leverage": [3, 5, 10][i % 3],
        "open_time": (_BASE_CLOSE + timedelta(hours=i * 6 - 2)).isoformat(),
        "close_time": (_BASE_CLOSE + timedelta(hours=i * 6)).isoformat(),
        "close_reason": "unknown",
    }
    for i, pnl in enumerate(_FROZEN_REPORTED_PNLS)
]

FROZEN_REPORTED_TOTAL_PNL = 49.23
FROZEN_WIN_COUNT = 48
FROZEN_LOSS_COUNT = 1
