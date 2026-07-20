"""Shared scan-verdict contract — separates BIAS from ACTIONABILITY.

This module is the single source of truth for what a scan is allowed to
conclude.  It mirrors the vocabulary of the realtime lifecycle
(``backend/realtime/lifecycle.py``): a typed state, explicit hard gates,
and a machine-readable list of blockers.  A confluence score may only
*rank* a setup after every hard gate passes — it can never turn a failed
gate into a trade.

Contract (``build_verdict`` return value)::

    {
      "schema_version": 1,
      "state":       "NO_TRADE" | "WATCH" | "READY_LONG" | "READY_SHORT",
      "display":     human label, e.g. "NO TRADE TODAY",
      "bias":        "LONG" | "SHORT" | "NEUTRAL",   # which way it leans
      "actionable":  bool,                            # True only for READY_*
      "gates":       [{id, label, passed, detail} x5],
      "blockers":    [str, ...],                      # failed-gate summaries
      "reasoning":   str,                             # human explanation
      "next_review": str,
    }

The five hard gates, in methodology order:

1. ``regime``     — weekly Bull Market Support Band regime known and matching
2. ``structure``  — weekly/daily/4H market structure all aligned
3. ``momentum``   — daily/4H/1H QQE trends all aligned
4. ``zone``       — a direction-matched 4H order block within pullback range
5. ``risk``       — plan has stop + 2R target with no detected opposing
                    order block sitting before the 2R target
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

SCHEMA_VERSION = 1

STRUCTURE_TFS = ("weekly", "daily", "4h")
MOMENTUM_TFS = ("daily", "4h", "1h")
BULL_LABELS = {"HH", "HL"}
BEAR_LABELS = {"LL", "LH"}

#: Votes needed (out of 7: regime + 3 structure TFs + 3 QQE TFs) before a
#: soft bias is reported when the hard direction gate has not passed.
BIAS_SUPERMAJORITY = 5


class ScanVerdict(str, Enum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    READY_LONG = "READY_LONG"
    READY_SHORT = "READY_SHORT"


class Bias(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


DISPLAY_LABELS = {
    ScanVerdict.NO_TRADE: "NO TRADE TODAY",
    ScanVerdict.WATCH: "WATCH — WAIT FOR CONFIRMATION",
    ScanVerdict.READY_LONG: "READY LONG",
    ScanVerdict.READY_SHORT: "READY SHORT",
}

NEXT_REVIEW_DEFAULT = "next 4H candle close"


@dataclass
class Gate:
    id: str
    label: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "passed": self.passed,
            "detail": self.detail,
        }


def derive_bias(
    labels: dict[str, str],
    trends: dict[str, str],
    regime: str | None,
) -> Bias:
    """Soft directional lean when the hard direction gate has not passed.

    One vote per signal (regime, each structure TF, each QQE TF — 7 total);
    a bias is reported only on a supermajority so a mixed tape stays NEUTRAL.
    """
    long_votes = 0
    short_votes = 0
    if regime == "bull":
        long_votes += 1
    elif regime == "bear":
        short_votes += 1
    for label in labels.values():
        if label in BULL_LABELS:
            long_votes += 1
        elif label in BEAR_LABELS:
            short_votes += 1
    for trend in trends.values():
        if trend == "GREEN":
            long_votes += 1
        elif trend == "RED":
            short_votes += 1
    if long_votes >= BIAS_SUPERMAJORITY and long_votes > short_votes:
        return Bias.LONG
    if short_votes >= BIAS_SUPERMAJORITY and short_votes > long_votes:
        return Bias.SHORT
    return Bias.NEUTRAL


def _normalized_zones(order_blocks: list[dict[str, Any]] | None) -> list[tuple[str, float, float]]:
    """Yield (type, low, high) for every well-formed order block."""
    zones: list[tuple[str, float, float]] = []
    for ob in order_blocks or []:
        if not isinstance(ob, dict):
            continue
        zone = ob.get("zone", (None, None))
        if not isinstance(zone, (tuple, list)) or len(zone) < 2:
            continue
        if zone[0] is None or zone[1] is None:
            continue
        low, high = sorted((float(zone[0]), float(zone[1])))
        zones.append((str(ob.get("type", "")).lower(), low, high))
    return zones


def _risk_gate(
    direction: str | None,
    entry_actionable: bool,
    price_levels: dict[str, Any],
    order_blocks: list[dict[str, Any]] | None,
) -> Gate:
    """Stop + 2R target present, with no opposing order block before the 2R target.

    Opposing zones come from the same detected 4H order-block set used for
    entries, so "clear" means clear of *detected* zones — an honest but
    bounded check until zones carry full metadata.
    """
    gate_id, label = "risk", "2R room"
    stop = price_levels.get("stop_loss")
    tp2 = price_levels.get("take_profit_2")
    entry = price_levels.get("entry_zone_low") or price_levels.get("current_price")

    if direction is None:
        return Gate(gate_id, label, False, "n/a — no directional plan to assess")
    if not entry_actionable:
        return Gate(gate_id, label, False, "n/a — no actionable entry zone")
    if stop is None or tp2 is None or entry is None:
        return Gate(gate_id, label, False, "plan is missing stop or 2R target levels")

    is_long = direction.upper() == "LONG"
    opposing_type = "bearish" if is_long else "bullish"
    blocking_level: float | None = None
    for ob_type, low, high in _normalized_zones(order_blocks):
        if ob_type != opposing_type:
            continue
        if is_long and low > entry:
            if low < tp2:
                blocking_level = low if blocking_level is None else min(blocking_level, low)
        elif not is_long and high < entry:
            if high > tp2:
                blocking_level = high if blocking_level is None else max(blocking_level, high)
    if blocking_level is not None:
        side = "supply" if is_long else "demand"
        return Gate(
            gate_id,
            label,
            False,
            f"2R target {tp2:.2f} sits beyond {side} at {blocking_level:.2f} — insufficient room",
        )
    return Gate(gate_id, label, True, f"stop {float(stop):.2f} and 2R target {float(tp2):.2f} clear of detected opposing zones")


def build_verdict(
    *,
    direction: str | None,
    entry_actionable: bool,
    structure_results: dict[str, Any],
    qqe_signals: dict[str, Any],
    bmsb_data: dict[str, Any] | None,
    price_levels: dict[str, Any],
    order_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the typed verdict payload for one scan.

    ``direction`` must come from the hard direction gate
    (``_determine_trade_direction``): a non-None value means regime,
    structure, and momentum already agree.
    """
    labels = {
        tf: str(structure_results.get(tf, {}).get("label", "")).upper()
        for tf in STRUCTURE_TFS
    }
    trends = {
        tf: str(qqe_signals.get(tf, {}).get("trend", "")).upper()
        for tf in MOMENTUM_TFS
    }
    regime = str((bmsb_data or {}).get("regime", "")).lower() or None

    bias = Bias(direction) if direction in ("LONG", "SHORT") else derive_bias(labels, trends, regime)
    ref_side = direction or (bias.value if bias is not Bias.NEUTRAL else None)

    structure_actual = ", ".join(f"{tf}={labels[tf] or '?'}" for tf in STRUCTURE_TFS)
    momentum_actual = ", ".join(f"{tf}={trends[tf] or '?'}" for tf in MOMENTUM_TFS)

    # ── Gate 1: regime ────────────────────────────────────────────────
    if regime not in ("bull", "bear"):
        regime_gate = Gate("regime", "Weekly BMSB regime", False, "weekly BMSB unavailable — regime unknown")
    elif ref_side is None:
        regime_gate = Gate("regime", "Weekly BMSB regime", False, f"regime={regime} but structure/momentum give no coherent direction")
    else:
        wanted = "bull" if ref_side == "LONG" else "bear"
        regime_gate = Gate(
            "regime", "Weekly BMSB regime", regime == wanted,
            f"regime={regime}" + ("" if regime == wanted else f" — conflicts with {ref_side} lean"),
        )

    # ── Gate 2: structure ─────────────────────────────────────────────
    if ref_side == "LONG":
        structure_ok = all(l in BULL_LABELS for l in labels.values())
    elif ref_side == "SHORT":
        structure_ok = all(l in BEAR_LABELS for l in labels.values())
    else:
        structure_ok = False
    structure_gate = Gate("structure", "Multi-TF structure", structure_ok, structure_actual)

    # ── Gate 3: momentum ──────────────────────────────────────────────
    if ref_side == "LONG":
        momentum_ok = all(t == "GREEN" for t in trends.values())
    elif ref_side == "SHORT":
        momentum_ok = all(t == "RED" for t in trends.values())
    else:
        momentum_ok = False
    momentum_gate = Gate("momentum", "Multi-TF QQE momentum", momentum_ok, momentum_actual)

    # ── Gate 4: zone ──────────────────────────────────────────────────
    zone_low = price_levels.get("entry_zone_low")
    zone_high = price_levels.get("entry_zone_high")
    if entry_actionable and zone_low is not None and zone_high is not None:
        zone_gate = Gate("zone", "Actionable entry zone", True, f"direction-matched 4H order block at {zone_low:.2f}–{zone_high:.2f}")
    else:
        zone_gate = Gate("zone", "Actionable entry zone", False, "no direction-matched 4H order block within 3% of price")

    # ── Gate 5: risk (2R room) ────────────────────────────────────────
    risk_gate = _risk_gate(direction, entry_actionable, price_levels, order_blocks)

    gates = [regime_gate, structure_gate, momentum_gate, zone_gate, risk_gate]

    # ── State ─────────────────────────────────────────────────────────
    if direction is None:
        state = ScanVerdict.NO_TRADE
    elif not entry_actionable or not risk_gate.passed:
        state = ScanVerdict.WATCH
    else:
        state = ScanVerdict.READY_LONG if direction == "LONG" else ScanVerdict.READY_SHORT

    blockers = [f"{g.label}: {g.detail}" for g in gates if not g.passed]

    # ── Reasoning ─────────────────────────────────────────────────────
    if state in (ScanVerdict.READY_LONG, ScanVerdict.READY_SHORT):
        reasoning = (
            f"{direction} setup confirmed: regime, structure, and momentum are aligned, "
            f"a direction-matched zone is within pullback range, and the 2R target has room."
        )
    elif state is ScanVerdict.WATCH and not entry_actionable:
        reasoning = (
            f"{direction} context is confirmed, but there is no direction-matched 4H order block "
            f"within the 3% actionable range. Wait for a pullback into a valid zone."
        )
    elif state is ScanVerdict.WATCH:
        reasoning = (
            f"{direction} context and entry zone are confirmed, but {risk_gate.detail}. "
            f"Wait for better location or a cleared path."
        )
    else:
        reasoning = (
            f"No coherent direction: regime={regime or 'unknown'}; structure {structure_actual}; "
            f"QQE {momentum_actual}."
        )
        if bias is not Bias.NEUTRAL:
            reasoning += f" Bias leans {bias.value} without full confirmation — do not front-run it."

    return {
        "schema_version": SCHEMA_VERSION,
        "state": state.value,
        "display": DISPLAY_LABELS[state],
        "bias": bias.value,
        "actionable": state in (ScanVerdict.READY_LONG, ScanVerdict.READY_SHORT),
        "gates": [g.to_dict() for g in gates],
        "blockers": blockers,
        "reasoning": reasoning,
        "next_review": NEXT_REVIEW_DEFAULT,
    }
