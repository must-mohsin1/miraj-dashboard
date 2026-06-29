"""
Trade plan generator with RSI three-entry system.

Generates structured trade plans when confluence score >= 10.
Includes RSI 3-entry system + DCA strategy + risk management rules.
"""
from __future__ import annotations

from typing import Any

from mirai_core import config


def generate_trade_plan(
    confluence_result: Any,
    data: dict[str, Any] | None = None,
    direction: str = "LONG",
    rsi_current: float | None = None,
) -> dict[str, Any]:
    """Generate a trade plan from confluence scoring result.

    Args:
        confluence_result: ConfluenceResult or similar with total and trade_decision.
        data: Optional dict with price levels, support/resistance, etc.
        direction: 'LONG' or 'SHORT'.
        rsi_current: Current RSI value for entry level guidance.

    Returns:
        dict with keys: trade_decision, direction, entry_plan, stop_loss,
        take_profit_targets, risk_management, reasoning.
    """
    trade_decision = bool(
        getattr(confluence_result, "trade_decision", False)
        or confluence_result.total >= config.SCORE_TRADE_THRESHOLD
    )

    if not trade_decision:
        return {
            "trade_decision": False,
            "verdict": "NO TRADE TODAY",
            "reasoning": (
                f"Confluence score {confluence_result.total:.1f} < "
                f"{config.SCORE_TRADE_THRESHOLD}. "
                "Not enough confirming factors for a trade."
            ),
            "watch_triggers": _generate_watch_triggers(data),
        }

    if data is None:
        data = {}

    entry_zone_low = data.get("entry_zone_low")
    entry_zone_high = data.get("entry_zone_high")
    stop_loss = data.get("stop_loss")
    tp1 = data.get("take_profit_1")
    tp2 = data.get("take_profit_2")

    # RSI three-entry system
    if direction == "LONG":
        thresholds = config.RSI_ENTRY_THRESHOLDS  # (30, 24, 16)
        allocations = config.RSI_ENTRY_ALLOCATIONS  # (20%, 20%, 60%)
        entries = []
        for i, (thresh, alloc) in enumerate(zip(thresholds, allocations)):
            entries.append(
                {
                    "entry": f"Entry {i + 1}",
                    "trigger": f"RSI hits {thresh}",
                    "position_size": f"{alloc * 100:.0f}%",
                    "rsi_target": thresh,
                }
            )
    else:  # SHORT
        thresholds = (
            config.RSI_SHORT_ENTRY_L1,
            config.RSI_SHORT_ENTRY_L2,
            config.RSI_SHORT_ENTRY_L3,
        )
        allocations = config.RSI_ENTRY_ALLOCATIONS
        entries = []
        for i, (thresh, alloc) in enumerate(zip(thresholds, allocations)):
            entries.append(
                {
                    "entry": f"Entry {i + 1}",
                    "trigger": f"RSI hits {thresh}",
                    "position_size": f"{alloc * 100:.0f}%",
                    "rsi_target": thresh,
                }
            )

    # Risk management rules
    risk_mgmt = [
        "Use DCA — split entries, don't enter full position at once",
        f"Risk 0.5-1% of portfolio per trade",
        "When investment DOUBLES → withdraw initial capital (play with house money)",
        "Set daily profit target → STOP after hitting it",
        "Wait for candle CLOSE confirmation — don't enter at current price",
    ]
    if direction == "LONG":
        risk_mgmt.append(
            f"Invalidation: weekly close below Bull Market Support Band"
        )
    else:
        risk_mgmt.append(
            "Invalidation: weekly close above previous swing high"
        )

    return {
        "trade_decision": True,
        "direction": direction,
        "confluence_score": round(confluence_result.total, 1),
        "entry_zone": {
            "low": entry_zone_low,
            "high": entry_zone_high,
            "description": (
                f"4H OTE zone {entry_zone_low:.2f}-{entry_zone_high:.2f}"
                if entry_zone_low and entry_zone_high
                else "Wait for 4H OTE zone to be identified"
            ),
        },
        "stop_loss": stop_loss,
        "take_profit_targets": [
            {"target": "TP1", "level": tp1, "description": "1R at 4H supply/demand"},
            {
                "target": "TP2",
                "level": tp2,
                "description": "2R+ at next supply/demand",
            },
        ],
        "rsi_entry_system": {
            "current_rsi": rsi_current,
            "entries": entries,
        },
        "dca_strategy": [
            "Don't enter full position at once",
            "Split into 3 entries based on RSI levels",
            "Average cost down as price moves deeper into the zone",
        ],
        "risk_management": risk_mgmt,
        "confirmations_met": _extract_confirmations(confluence_result),
    }


def _generate_watch_triggers(data: dict[str, Any] | None) -> list[str]:
    """Generate direction-neutral watch triggers when no trade."""
    triggers = [
        "HTF structure alignment (weekly/daily)",
        "Price reaching 4H OTE zone (0.62-0.705 fib)",
        "QQE Mod turning GREEN (longs) or RED (shorts)",
        "RSI divergence forming",
        "Bull Market Support Band test (BTC only)",
        "Volume confirmation on breakout",
    ]
    if data:
        if data.get("weekly_structure_pending"):
            triggers.insert(
                0, "Weekly structure turns bullish/bearish to align with direction"
            )
    return triggers


def _extract_confirmations(confluence_result: Any) -> list[str]:
    """Build a human-readable list of confirmations that were met."""
    confirmed: list[str] = []
    try:
        breakdowns = [
            ("regime", confluence_result.regime_breakdown),
            ("location", confluence_result.location_breakdown),
            ("confirmation", confluence_result.confirmation_breakdown),
            ("volume_retest", confluence_result.volume_retest_breakdown),
            ("risk", confluence_result.risk_breakdown),
        ]
        for category, bd in breakdowns:
            for key, val in bd.items():
                if val:
                    confirmed.append(f"{category}:{key}")
    except AttributeError:
        pass
    return confirmed if confirmed else ["Confluence threshold met"]
