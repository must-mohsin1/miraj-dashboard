"""Dynamic DCA service — position-aware Dollar Cost Averaging engine.

For every open position, this module fetches (or runs) the latest Miraj scan for
that symbol and computes an actionable recommendation: ADD / HOLD / REDUCE / CLOSE.

Decision hierarchy (see docs/DYNAMIC_DCA_IMPLEMENTATION.md §3):
    1. Hard exits   — liquidation proximity, confluence flip, BMSB regime
    2. Profit-taking — +100% PnL, TP1/TP2 hit
    3. QQE conflicts — daily+4H both against, or only 4H
    4. DCA disabled  — BB squeezing, no QQE aligned, confluence < 10, opposite pattern
    5. Zone-based ADD — price in OTE + QQE aligned (RSI oversold boosts confidence)
    6. Default        — HOLD (LOW)

Reuses the scan-fetching pattern from ``position_alert_service.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.services.analysis_service import get_cached_or_none, run_scan
from backend.services.position_alert_service import normalize_to_scan_symbol

logger = logging.getLogger(__name__)

# ── Miraj constants (mirror mirai_core.config for the DCA engine) ──
RSI_ENTRY_THRESHOLDS_LONG = (30, 24, 16)
RSI_ENTRY_THRESHOLDS_SHORT = (80, 92, 95)
RSI_ENTRY_ALLOCATIONS = (0.20, 0.20, 0.60)
SCORE_TRADE_THRESHOLD = 10


# ════════════════════════════════════════════════════════════════════════════
# Data extraction helpers
# ════════════════════════════════════════════════════════════════════════════


def _series_last(series: Any) -> Optional[float]:
    """Safely extract the last float value from a pandas-like object."""
    if series is None:
        return None
    if hasattr(series, "iloc") and len(series) > 0:
        try:
            val = float(series.iloc[-1])
            return val if val == val else None  # NaN guard
        except (TypeError, ValueError, IndexError):
            return None
    if isinstance(series, (int, float)):
        val = float(series)
        return val if val == val else None
    return None


def _current_rsi(scan: Dict[str, Any], timeframe: str = "daily") -> Optional[float]:
    """Extract the latest RSI value for a given timeframe from the scan."""
    indicators = scan.get("indicators") if isinstance(scan, dict) else None
    if not isinstance(indicators, dict):
        return None
    tf_data = indicators.get(timeframe)
    if not isinstance(tf_data, dict) or tf_data.get("error"):
        return None
    rsi_val = tf_data.get("rsi")
    return float(rsi_val) if isinstance(rsi_val, (int, float)) else None


def _rsi_all_tf(scan: Dict[str, Any]) -> Dict[str, float]:
    """Return ``{daily, 4h, 1h, 15m}`` RSI values (dict may be partial)."""
    out: Dict[str, float] = {}
    indicators = scan.get("indicators") if isinstance(scan, dict) else None
    if not isinstance(indicators, dict):
        return out
    for tf in ("daily", "4h", "1h", "15m"):
        tf_data = indicators.get(tf)
        if not isinstance(tf_data, dict) or tf_data.get("error"):
            continue
        rsi_val = tf_data.get("rsi")
        if isinstance(rsi_val, (int, float)):
            out[tf] = float(rsi_val)
    return out


def _qqe_trends(scan: Dict[str, Any]) -> Dict[str, str]:
    """Return ``{daily, 4h, 1h} -> 'GREEN'/'RED'/'NEUTRAL'``."""
    out: Dict[str, str] = {}
    qqe_signals = scan.get("qqe_signals") if isinstance(scan, dict) else None
    if not isinstance(qqe_signals, dict):
        return out
    for tf in ("daily", "4h", "1h"):
        sig = qqe_signals.get(tf)
        if isinstance(sig, dict):
            out[tf] = (sig.get("trend") or "NEUTRAL").upper()
        else:
            out[tf] = "NEUTRAL"
    return out


def _structure_labels(scan: Dict[str, Any]) -> Dict[str, str]:
    """Return ``{weekly, daily, 4h, 1h, 15m} -> 'HH'/'HL'/'LH'/'LL'/''``."""
    out: Dict[str, str] = {}
    structure = scan.get("structure") if isinstance(scan, dict) else None
    if not isinstance(structure, dict):
        return out
    for tf in ("weekly", "daily", "4h", "1h", "15m"):
        tf_struct = structure.get(tf)
        if isinstance(tf_struct, dict):
            label = (tf_struct.get("label") or "").upper()
            if label in ("HH", "HL", "LH", "LL"):
                out[tf] = label
            else:
                out[tf] = ""
        else:
            out[tf] = ""
    return out


def _bb_squeeze_any(scan: Dict[str, Any]) -> bool:
    """Return True if Bollinger Bands are squeezing on any timeframe."""
    indicators = scan.get("indicators") if isinstance(scan, dict) else None
    if not isinstance(indicators, dict):
        return False
    for tf_data in indicators.values():
        if isinstance(tf_data, dict) and tf_data.get("bb_squeeze", False) and not tf_data.get("error"):
            return True
    return False


def _ote_zone(scan: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Extract the OTE/entry zone ``(low, high)`` from the scan's trade plan.

    Looks at ``trade_plan.entry_zone`` first, then falls back to
    ``trade_plan_flat.entry`` + SMC order blocks.
    """
    if not isinstance(scan, dict):
        return None
    # 1. trade_plan.entry_zone
    tp = scan.get("trade_plan")
    if isinstance(tp, dict):
        ez = tp.get("entry_zone")
        if isinstance(ez, dict):
            low, high = ez.get("low"), ez.get("high")
            if low is not None and high is not None and low > 0 and high >= low:
                return (float(low), float(high))
        # explicit TP prices at top level
        tp1 = tp.get("tp1_price")
        tp2 = tp.get("tp2_price")
        if tp1 is not None and tp2 is not None:
            return (float(tp1), float(tp2))
    # 2. trade_plan_flat
    flat = scan.get("trade_plan_flat")
    if isinstance(flat, dict):
        entry = flat.get("entry")
        target1 = flat.get("target_1")
        if entry is not None and target1 is not None:
            lo = float(entry)
            hi = float(target1)
            return (min(lo, hi), max(lo, hi))
    # 3. SMC order blocks (first bullish OB zone)
    smc_data = scan.get("smc")
    if isinstance(smc_data, dict):
        obs = smc_data.get("order_blocks")
        if isinstance(obs, list) and obs:
            for ob in obs:
                if isinstance(ob, dict):
                    zone = ob.get("zone")
                    if isinstance(zone, (list, tuple)) and len(zone) >= 2 and zone[0] is not None and zone[1] is not None:
                        return (float(zone[0]), float(zone[1]))
    return None


def _confluence_score(scan: Dict[str, Any]) -> float:
    """Return the confluence score (0-30) from the scan."""
    if not isinstance(scan, dict):
        return 0.0
    score = scan.get("confluence_score")
    if isinstance(score, (int, float)):
        return float(score)
    return 0.0


def _scan_direction(scan: Dict[str, Any]) -> Optional[str]:
    """Infer the directional bias from the scan's trade plan."""
    if not isinstance(scan, dict):
        return None
    tp = scan.get("trade_plan")
    if isinstance(tp, dict):
        direction = tp.get("direction")
        if isinstance(direction, str) and direction.upper() in ("LONG", "SHORT"):
            return direction.upper()
        # trade_decision False = no direction
        if tp.get("trade_decision") is False:
            return None
    flat = scan.get("trade_plan_flat")
    if isinstance(flat, dict):
        direction = flat.get("direction")
        if isinstance(direction, str) and direction.upper() in ("LONG", "SHORT"):
            return direction.upper()
    return None


def _bmsb_status(scan: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{sma_20w, ema_21w, current_price, status, regime}`` from the scan."""
    bmsb = scan.get("bmsb") if isinstance(scan, dict) else None
    if isinstance(bmsb, dict):
        return bmsb
    return {
        "sma_20w": None,
        "ema_21w": None,
        "current_price": None,
        "status": "unknown",
        "regime": "unknown",
    }


def _chart_patterns(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return ``[{name, direction, confirmed}]`` for detected patterns."""
    out: List[Dict[str, Any]] = []
    if not isinstance(scan, dict):
        return out
    patterns_data = scan.get("patterns")
    if not isinstance(patterns_data, dict):
        return out
    detected = patterns_data.get("detected")
    if not isinstance(detected, list):
        return out
    for p in detected:
        if not isinstance(p, dict):
            continue
        name = p.get("pattern") or p.get("name") or ""
        signal = (p.get("signal") or "").upper()
        direction = "neutral"
        if "BEARISH" in signal or "BEAR" in signal:
            direction = "bearish"
        elif "BULLISH" in signal or "BULL" in signal:
            direction = "bullish"
        out.append({
            "name": name,
            "direction": direction,
            "confirmed": bool(p.get("confirmed", False)),
        })
    return out


def _trade_plan_tp_levels(scan: Dict[str, Any]) -> List[float]:
    """Return ``[tp1, tp2]`` price levels from the scan's trade plan."""
    if not isinstance(scan, dict):
        return []
    tp = scan.get("trade_plan")
    levels: List[float] = []
    # explicit top-level fields first (added by DCA engine changes)
    if isinstance(tp, dict):
        tp1 = tp.get("tp1_price")
        tp2 = tp.get("tp2_price")
        if tp1 is not None:
            levels.append(float(tp1))
        if tp2 is not None:
            levels.append(float(tp2))
        if levels:
            return levels
    # fallback: take_profit_targets list
    if isinstance(tp, dict):
        tps = tp.get("take_profit_targets")
        if isinstance(tps, list):
            for tgt in tps[:2]:
                if isinstance(tgt, dict) and tgt.get("level") is not None:
                    levels.append(float(tgt["level"]))
            if levels:
                return levels
    # fallback: trade_plan_flat targets
    flat = scan.get("trade_plan_flat")
    if isinstance(flat, dict):
        if flat.get("target_1") is not None:
            levels.append(float(flat["target_1"]))
        if flat.get("target_2") is not None:
            levels.append(float(flat["target_2"]))
    return levels


# ════════════════════════════════════════════════════════════════════════════
# Adaptive RSI entry ladder
# ════════════════════════════════════════════════════════════════════════════


def compute_adaptive_entries(
    direction: str,
    rsi_current: Optional[float],
    rsi_at_entry: Optional[float],
    entry_price: float,
    ote_zone: Optional[Tuple[float, float]],
    position_budget_pct: float,
) -> List[Dict[str, Any]]:
    """Compute DCA entry levels ADAPTED to the user's actual entry.

    - If user entered at RSI 45 → ladder shifts to zone-based for Entry 1
    - If user entered at RSI 18 → all entries FILLED, no more DCA
    - RSI levels become secondary to OTE zone proximity

    Returns list of:
        {entry, trigger, position_size_pct, cumulative_pct,
         status, trigger_type, rsi_target, level_price}
    """
    is_long = direction.upper() == "LONG"
    thresholds = RSI_ENTRY_THRESHOLDS_LONG if is_long else RSI_ENTRY_THRESHOLDS_SHORT

    rsi_entry = rsi_at_entry
    cumulative = 0.0
    entries: List[Dict[str, Any]] = []

    for i, (thresh, alloc) in enumerate(zip(thresholds, RSI_ENTRY_ALLOCATIONS)):
        cumulative += alloc
        # Determine if this entry level was already "filled" at entry time
        filled = False
        if rsi_entry is not None:
            if is_long and rsi_entry <= thresh:
                filled = True
            elif not is_long and rsi_entry >= thresh:
                filled = True

        # Trigger type: zone for the first entry when user entered above threshold
        trigger_type = "rsi"
        trigger_text = f"RSI hits {thresh}"
        level_price: Optional[float] = None

        if i == 0 and ote_zone is not None and rsi_entry is not None:
            # If user entered above the first RSI trigger, Entry 1 becomes zone-based
            entered_above = rsi_entry > thresh if is_long else rsi_entry < thresh
            if entered_above:
                trigger_type = "zone"
                lo, hi = ote_zone
                trigger_text = f"Price returns to OTE zone {lo:.2f}-{hi:.2f}"
                level_price = round((lo + hi) / 2, 2)

        entries.append({
            "entry": f"Entry {i + 1}",
            "trigger": trigger_text,
            "position_size_pct": f"{int(alloc * 100)}%",
            "cumulative_pct": f"{int(cumulative * 100)}%",
            "status": "filled" if filled else "pending",
            "trigger_type": trigger_type,
            "rsi_target": thresh,
            "level_price": level_price,
        })

    # Adjust deployment ratio based on what was already deployed
    deployed = max(0.0, min(position_budget_pct, 1.0))
    if deployed >= 1.0:
        # Full position deployed — all filled regardless of RSI at entry
        for e in entries:
            e["status"] = "filled"

    return entries


# ════════════════════════════════════════════════════════════════════════════
# Core evaluation
# ════════════════════════════════════════════════════════════════════════════


def evaluate_dca(
    position: Dict[str, Any],
    scan: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Decision tree for a single position vs scan.

    Position must have: symbol, side, size, entry_price, mark_price,
    pnl, pnl_percent, leverage, liquidation_price, margin.

    Returns a dict with recommendation, reason, confidence, and supporting data.
    """
    symbol = position.get("symbol", "")
    side = (position.get("side") or "").upper()
    is_long = side in ("LONG", "BUY")
    is_short = side in ("SHORT", "SELL")
    position_dir = "LONG" if is_long else "SHORT"
    opposite_dir = "SHORT" if is_long else "LONG"

    entry_price = float(position.get("entry_price") or 0)
    mark_price = float(position.get("mark_price") or entry_price or 0)
    pnl_pct = float(position.get("pnl_percent") or 0)
    leverage = float(position.get("leverage") or 1)
    liq_price = position.get("liquidation_price")
    size = float(position.get("size") or 0)
    pnl = float(position.get("pnl") or 0)

    # Defaults
    confidence = "LOW"
    risk_rules: List[str] = []
    future_add_triggers: List[str] = []
    action_items: List[str] = []

    # Risk rules always included
    risk_rules = [
        "Risk 0.5-1% of portfolio per trade",
        "When investment DOUBLES → withdraw initial capital",
        "Use DCA — split entries, don't enter full position at once",
        "Wait for candle CLOSE confirmation — don't enter at current price",
    ]

    # ── Empty / no-scan fallback ─────────────────────────────────────
    if scan is None:
        return {
            "symbol": symbol,
            "position_side": position_dir,
            "entry_price": entry_price,
            "mark_price": mark_price,
            "pnl": pnl,
            "pnl_percent": pnl_pct,
            "leverage": leverage,
            "recommendation": "HOLD",
            "reason": "Scan unavailable — cannot evaluate DCA signals.",
            "confidence": "LOW",
            "rsi_current": None,
            "rsi_entries": [],
            "next_entry": None,
            "dca_zone": None,
            "tp_levels": [],
            "risk_rules": risk_rules,
            "future_add_triggers": future_add_triggers,
            "action_items": action_items,
        }

    if not is_long and not is_short:
        return {
            "symbol": symbol,
            "position_side": position_dir,
            "entry_price": entry_price,
            "mark_price": mark_price,
            "pnl": pnl,
            "pnl_percent": pnl_pct,
            "leverage": leverage,
            "recommendation": "HOLD",
            "reason": "Unknown position direction — cannot evaluate.",
            "confidence": "LOW",
            "rsi_current": None,
            "rsi_entries": [],
            "next_entry": None,
            "dca_zone": None,
            "tp_levels": [],
            "risk_rules": risk_rules,
            "future_add_triggers": [],
            "action_items": [],
        }

    # ── Extract scan data ────────────────────────────────────────────
    rsi_current = _current_rsi(scan, "daily")
    rsi = rsi_current
    if rsi is None:
        rsi_all = _rsi_all_tf(scan)
        rsi = rsi_all.get("daily")
        if rsi is not None:
            rsi_current = rsi

    qqe = _qqe_trends(scan)
    structure = _structure_labels(scan)
    bb_squeeze = _bb_squeeze_any(scan)
    ote = _ote_zone(scan)
    confluence = _confluence_score(scan)
    scan_dir = _scan_direction(scan)
    bmsb = _bmsb_status(scan)
    patterns_detected = _chart_patterns(scan)
    tp_levels = _trade_plan_tp_levels(scan)

    # Determine QQE alignment/conflicts
    bull_qqes = sum(1 for tf in ("daily", "4h", "1h") if qqe.get(tf, "NEUTRAL") == "GREEN")
    bear_qqes = sum(1 for tf in ("daily", "4h", "1h") if qqe.get(tf, "NEUTRAL") == "RED")
    any_qqe_aligned = (bull_qqes > 0 and is_long) or (bear_qqes > 0 and is_short)
    daily_qqe_against = (qqe.get("daily", "NEUTRAL") == "RED" and is_long) or (
        qqe.get("daily", "NEUTRAL") == "GREEN" and is_short
    )
    h4_qqe_against = (qqe.get("4h", "NEUTRAL") == "RED" and is_long) or (
        qqe.get("4h", "NEUTRAL") == "GREEN" and is_short
    )
    conflicting_qqes = (1 if daily_qqe_against else 0) + (1 if h4_qqe_against else 0)

    # Structure conflicts
    bearish_struct_count = sum(
        1 for tf in ("weekly", "daily", "4h") if structure.get(tf) in ("LH", "LL")
    )
    bullish_struct_count = sum(
        1 for tf in ("weekly", "daily", "4h") if structure.get(tf) in ("HH", "HL")
    )
    struct_conflicts = (bearish_struct_count if is_long else bullish_struct_count)
    total_conflicts = conflicting_qqes + struct_conflicts

    # BMSB status
    bmsb_status = (bmsb.get("status") or "unknown").lower()
    bmsb_bear = bmsb_status == "below"

    # Opposite pattern check
    opposite_pattern_name = None
    for p in patterns_detected:
        is_opposite = (p["direction"] == "bearish" and is_long) or (
            p["direction"] == "bullish" and is_short
        )
        if is_opposite and p["confirmed"]:
            opposite_pattern_name = p["name"]
            break

    # ── STEP 1: Hard exits ──────────────────────────────────────────
    # 1a. liquidation distance < 2%
    if liq_price is not None and mark_price > 0 and liq_price > 0:
        liq_distance = abs(mark_price - liq_price) / mark_price * 100.0
        if liq_distance < 2.0:
            reason = (
                f"Mark price only {liq_distance:.1f}% from liquidation "
                f"({mark_price:.4f} → liq {liq_price:.4f}). CLOSE immediately."
            )
            action_items.append("Close position immediately — liquidation imminent")
            confidence = "CRITICAL"
            return _build_dca_result(
                position=dict(position), symbol=symbol, position_dir=position_dir,
                entry_price=entry_price, mark_price=mark_price, pnl=pnl,
                pnl_pct=pnl_pct, leverage=leverage,
                recommendation="CLOSE", reason=reason, confidence=confidence,
                rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
                risk_rules=risk_rules, future_add_triggers=[],
                action_items=action_items, ote_zone=ote,
            )

    # 1b. scan_direction opposite + 3+ conflicts
    if scan_dir is not None and scan_dir == opposite_dir and total_conflicts >= 3:
        reason = (
            f"Scan direction is {scan_dir} (opposite to {position_dir}) "
            f"with {total_conflicts} conflicting signals. CLOSE — confluence flipped."
        )
        action_items.append(f"Close {position_dir} position — confluence flipped to {scan_dir}")
        confidence = "CRITICAL"
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="CLOSE", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=[],
            action_items=action_items, ote_zone=ote,
        )

    # 1c. BMSB below + is_long → REDUCE
    if bmsb_bear and is_long:
        bmsb_band = bmsb.get("sma_20w") or bmsb.get("ema_21w")
        reason = (
            f"Below Bull Market Support Band ({bmsb_band}) — bear regime. "
            f"REDUCE {position_dir} exposure."
        )
        half_size = max(1, size // 2)
        action_items.append(f"Reduce {int(half_size)} of {int(size)} contracts — below BMSB")
        confidence = "HIGH"
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="REDUCE", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=[],
            action_items=action_items, ote_zone=ote,
        )

    # ── STEP 2: Profit-taking ───────────────────────────────────────
    # 2a. pnl_pct >= 100% → REDUCE (HIGH) — withdraw initial capital
    if pnl_pct >= 100.0:
        reason = (
            f"Position is up +{pnl_pct:.1f}% — investment has DOUBLED. "
            f"REDUCE: withdraw initial capital, play with house money."
        )
        half_size = max(1, size // 2)
        action_items.append(f"Close {int(half_size)} of {int(size)} contracts — take profit at +{pnl_pct:.0f}%")
        confidence = "HIGH"
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="REDUCE", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=[],
            action_items=action_items, ote_zone=ote,
        )

    # 2b. price >= TP1 (long) / <= TP1 (short) → REDUCE 50%
    if tp_levels and len(tp_levels) >= 1 and tp_levels[0] is not None:
        tp1 = tp_levels[0]
        tp1_hit = (is_long and mark_price >= tp1) or (not is_long and mark_price <= tp1)
        if tp1_hit:
            # Check for additional bearish/conflicting factors
            additional_reasons = []
            if h4_qqe_against:
                additional_reasons.append("QQE 4H against")
            if opposite_pattern_name:
                additional_reasons.append(f"{opposite_pattern_name} confirmed")
            if bmsb_bear and is_long:
                additional_reasons.append("below BMSB")
            extra = ". ".join(additional_reasons)

            reason = (
                f"TP1 hit (${tp1:.2f}). {extra}. "
                f"REDUCE 50% — take partial profits.".strip(". ")
            )
            half_size = max(1, size // 2)
            action_items.append(f"Close {int(half_size)} of {int(size)} contracts at ~${mark_price:.2f} (TP1 hit)")
            # Stop loss suggestion: use entry_price as fallback for zone
            stop_level = entry_price * (0.97 if is_long else 1.03)
            action_items.append(f"Move stop to ${stop_level:.2f} (lock in partial gains)")
            if h4_qqe_against:
                future_add_triggers.append("4H QQE must turn GREEN" if is_long else "4H QQE must turn RED")
            confidence = "HIGH"
            return _build_dca_result(
                position=dict(position), symbol=symbol, position_dir=position_dir,
                entry_price=entry_price, mark_price=mark_price, pnl=pnl,
                pnl_pct=pnl_pct, leverage=leverage,
                recommendation="REDUCE", reason=reason, confidence=confidence,
                rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
                risk_rules=risk_rules, future_add_triggers=future_add_triggers,
                action_items=action_items, ote_zone=ote,
            )

    # 2c. price >= TP2 → REDUCE remaining
    if tp_levels and len(tp_levels) >= 2 and tp_levels[1] is not None:
        tp2 = tp_levels[1]
        tp2_hit = (is_long and mark_price >= tp2) or (not is_long and mark_price <= tp2)
        if tp2_hit:
            reason = (
                f"TP2 hit (${tp2:.2f}) — target reached. "
                f"REDUCE: close remaining position."
            )
            action_items.append(f"Close remaining {int(size)} contracts — TP2 hit at ~${mark_price:.2f}")
            confidence = "HIGH"
            return _build_dca_result(
                position=dict(position), symbol=symbol, position_dir=position_dir,
                entry_price=entry_price, mark_price=mark_price, pnl=pnl,
                pnl_pct=pnl_pct, leverage=leverage,
                recommendation="REDUCE", reason=reason, confidence=confidence,
                rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
                risk_rules=risk_rules, future_add_triggers=[],
                action_items=action_items, ote_zone=ote,
            )

    # ── STEP 3: QQE conflicts ───────────────────────────────────────
    # 3a. Daily + 4H both against → REDUCE (HIGH)
    if daily_qqe_against and h4_qqe_against:
        reason = (
            f"Daily + 4H QQE both flipped against {position_dir} "
            f"(daily: {qqe.get('daily')}, 4H: {qqe.get('4h')}). "
            f"REDUCE — momentum is dying."
        )
        half_size = max(1, size // 2)
        action_items.append(f"Reduce {int(half_size)} of {int(size)} contracts — QQE flipped on HTF")
        confidence = "HIGH"
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="REDUCE", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=[
                "Wait for Daily + 4H QQE to realign before adding",
            ],
            action_items=action_items, ote_zone=ote,
        )

    # 3b. Only 4H against → HOLD (MEDIUM)
    if h4_qqe_against and not daily_qqe_against:
        reason = (
            f"4H QQE against {position_dir} but Daily still aligned. "
            f"HOLD — wait for LTF to resolve."
        )
        confidence = "MEDIUM"
        _append_zone_triggers(
            future_add_triggers, ote, is_long,
        )
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="HOLD", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=future_add_triggers,
            action_items=action_items, ote_zone=ote,
        )

    # ── STEP 4: DCA disabled ────────────────────────────────────────
    # 4a. BB squeezing → HOLD (MEDIUM)
    if bb_squeeze:
        reason = "Bollinger Bands squeezing on a timeframe — volatility compression. HOLD."
        confidence = "MEDIUM"
        future_add_triggers.append("Wait for BB expansion (volatility breakout)")
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="HOLD", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=future_add_triggers,
            action_items=action_items, ote_zone=ote,
        )

    # 4b. No QQE aligned → HOLD (MEDIUM)
    if not any_qqe_aligned:
        reason = (
            f"No QQE signal aligned with {position_dir} on any timeframe. "
            f"HOLD — no momentum confirmation."
        )
        confidence = "MEDIUM"
        aligned_qqe_label = "GREEN" if is_long else "RED"
        future_add_triggers.append(f"At least one QQE must turn {aligned_qqe_label}")
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="HOLD", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=future_add_triggers,
            action_items=action_items, ote_zone=ote,
        )

    # 4c. Confluence < 10 → HOLD (MEDIUM)
    if confluence < SCORE_TRADE_THRESHOLD:
        reason = (
            f"Confluence score {confluence:.1f} < {SCORE_TRADE_THRESHOLD}. "
            f"HOLD — not enough confirming factors for DCA."
        )
        confidence = "MEDIUM"
        future_add_triggers.append(f"Confluence score must rise to >= {SCORE_TRADE_THRESHOLD}")
        _append_zone_triggers(future_add_triggers, ote, is_long)
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="HOLD", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=future_add_triggers,
            action_items=action_items, ote_zone=ote,
        )

    # 4d. Confirmed opposite pattern → HOLD (HIGH)
    if opposite_pattern_name:
        reason = (
            f"Confirmed {opposite_pattern_name} pattern ({'bearish' if is_long else 'bullish'}) "
            f"conflicts with {position_dir}. HOLD — pattern invalidation needed."
        )
        confidence = "HIGH"
        future_add_triggers.append(f"{opposite_pattern_name} pattern must invalidate")
        _append_zone_triggers(future_add_triggers, ote, is_long)
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="HOLD", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=future_add_triggers,
            action_items=action_items, ote_zone=ote,
        )

    # ── STEP 5: Zone-based ADD ──────────────────────────────────────
    price_in_ote = False
    if ote is not None and mark_price > 0:
        lo, hi = ote
        price_in_ote = lo <= mark_price <= hi

    rsi_oversold = False
    if rsi_current is not None:
        rsi_oversold = (rsi_current < 40) if is_long else (rsi_current > 60)

    # 5a. price in OTE + QQE aligned + RSI oversold → ADD (HIGH)
    if price_in_ote and any_qqe_aligned and rsi_oversold:
        lo, hi = ote  # type: ignore[misc]
        reason = (
            f"Price in OTE zone (${lo:.2f}-${hi:.2f}) + QQE aligned + RSI oversold ({rsi_current:.1f}). "
            f"ADD — high-confluence DCA zone."
        )
        action_items.append(
            f"Add 20% of remaining budget — price in OTE + RSI {rsi_current:.1f}"
        )
        confidence = "HIGH"
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="ADD", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=[],
            action_items=action_items, ote_zone=ote,
        )

    # 5b. price in OTE + QQE aligned → ADD (MEDIUM)
    if price_in_ote and any_qqe_aligned:
        lo, hi = ote  # type: ignore[misc]
        reason = (
            f"Price in OTE zone (${lo:.2f}-${hi:.2f}) + QQE aligned. "
            f"ADD — zone valid, momentum confirmed."
        )
        action_items.append(
            f"Add 20% of remaining budget — price in OTE zone ${lo:.2f}-${hi:.2f}"
        )
        confidence = "MEDIUM"
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="ADD", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=[],
            action_items=action_items, ote_zone=ote,
        )

    # 5c. RSI oversold but NOT in OTE → HOLD (MEDIUM)
    if rsi_oversold and not price_in_ote:
        reason = (
            f"RSI {rsi_current:.1f} is oversold but price NOT in OTE zone. "
            f"HOLD — RSI alone is not a DCA trigger (zone-first)."
        )
        confidence = "MEDIUM"
        if ote is not None:
            lo, hi = ote
            future_add_triggers.append(f"Price must return to OTE zone (${lo:.2f}-${hi:.2f})")
        aligned_qqe_label = "GREEN" if is_long else "RED"
        future_add_triggers.append(f"QQE must be {aligned_qqe_label} aligned")
        return _build_dca_result(
            position=dict(position), symbol=symbol, position_dir=position_dir,
            entry_price=entry_price, mark_price=mark_price, pnl=pnl,
            pnl_pct=pnl_pct, leverage=leverage,
            recommendation="HOLD", reason=reason, confidence=confidence,
            rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
            risk_rules=risk_rules, future_add_triggers=future_add_triggers,
            action_items=action_items, ote_zone=ote,
        )

    # ── STEP 6: Default → HOLD (LOW) ────────────────────────────────
    reason = "No DCA triggers met. HOLD — cash is a position."
    confidence = "LOW"
    _append_zone_triggers(future_add_triggers, ote, is_long)
    aligned_qqe_label = "GREEN" if is_long else "RED"
    future_add_triggers.append(f"QQE must turn {aligned_qqe_label} on at least one TF")
    return _build_dca_result(
        position=dict(position), symbol=symbol, position_dir=position_dir,
        entry_price=entry_price, mark_price=mark_price, pnl=pnl,
        pnl_pct=pnl_pct, leverage=leverage,
        recommendation="HOLD", reason=reason, confidence=confidence,
        rsi_current=rsi_current, scan=scan, ote=ote, tp_levels=tp_levels,
        risk_rules=risk_rules, future_add_triggers=future_add_triggers,
        action_items=action_items, ote_zone=ote,
    )


def _append_zone_triggers(
    triggers: List[str],
    ote: Optional[Tuple[float, float]],
    is_long: bool,
) -> None:
    """Append OTE-zone based future ADD triggers to the triggers list."""
    if ote is not None:
        lo, hi = ote
        triggers.append(f"Price must pull back to OTE zone (${lo:.2f}-${hi:.2f})")
    rsi_direction = "below 40" if is_long else "above 60"
    triggers.append(f"RSI must drop {rsi_direction}" if is_long else f"RSI must rise {rsi_direction}")


def _build_dca_result(
    position: Dict[str, Any],
    symbol: str,
    position_dir: str,
    entry_price: float,
    mark_price: float,
    pnl: float,
    pnl_pct: float,
    leverage: float,
    recommendation: str,
    reason: str,
    confidence: str,
    rsi_current: Optional[float],
    scan: Dict[str, Any],
    ote: Optional[Tuple[float, float]],
    tp_levels: List[float],
    risk_rules: List[str],
    future_add_triggers: List[str],
    action_items: List[str],
    ote_zone: Optional[Tuple[float, float]],
) -> Dict[str, Any]:
    """Build the final evaluate_dca result dict, including the adaptive ladder.

    Uses the scan's RSI as a proxy for rsi_at_entry when the position's
    entry RSI is unknown (Phase 1 approach per the implementation spec).
    """
    # Approximate deployed % — for Phase 1 we don't track fill history, so
    # we treat the position as having deployed the first entry (20%).
    position_budget_pct = 0.2

    # rsi_at_entry proxy: current scan's RSI (Phase 1 simplification)
    rsi_at_entry = rsi_current

    rsi_entries = compute_adaptive_entries(
        direction=position_dir,
        rsi_current=rsi_current,
        rsi_at_entry=rsi_at_entry,
        entry_price=entry_price,
        ote_zone=ote_zone,
        position_budget_pct=position_budget_pct,
    )

    next_entry = None
    for e in rsi_entries:
        if e["status"] == "pending":
            next_entry = e
            break

    dca_zone = None
    if ote is not None:
        lo, hi = ote
        dca_zone = {
            "low": lo,
            "high": hi,
            "label": f"OTE {lo:.2f}-{hi:.2f}",
        }

    return {
        "symbol": symbol,
        "position_side": position_dir,
        "entry_price": entry_price,
        "mark_price": mark_price,
        "pnl": pnl,
        "pnl_percent": pnl_pct,
        "leverage": leverage,
        "recommendation": recommendation,
        "reason": reason,
        "confidence": confidence,
        "rsi_current": rsi_current,
        "rsi_entries": rsi_entries,
        "next_entry": next_entry,
        "dca_zone": dca_zone,
        "tp_levels": tp_levels,
        "risk_rules": risk_rules,
        "future_add_triggers": future_add_triggers,
        "action_items": action_items,
    }


# ════════════════════════════════════════════════════════════════════════════
# Batch computation
# ════════════════════════════════════════════════════════════════════════════


async def _get_scan_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Return the latest scan result for *symbol* (a yfinance ticker).

    Tries the in-memory cache first (15-min TTL). If not cached, runs the
    full pipeline in a background thread. Returns ``None`` on failure.
    """
    cached = get_cached_or_none(symbol)
    if cached is not None:
        return cached
    try:
        result = await asyncio.to_thread(run_scan, symbol)
        return result
    except Exception as exc:
        logger.warning("DCA: scan failed for %s: %s", symbol, exc)
        return None


async def compute_dca_recommendations(
    positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compute DCA recommendations for all open positions.

    Reuses the position_alert_service pattern:
    - Normalize symbols (BTC/USDT:USDT → BTC-USD)
    - Fetch scans concurrently (Semaphore(3))
    - Evaluate each position against its scan
    """
    semaphore = asyncio.Semaphore(3)

    async def fetch_scan(pos_symbol: str) -> Optional[Dict[str, Any]]:
        scan_symbol = normalize_to_scan_symbol(pos_symbol)
        async with semaphore:
            return await _get_scan_for_symbol(scan_symbol)

    scan_tasks = [fetch_scan(p.get("symbol", "")) for p in positions]
    scans = await asyncio.gather(*scan_tasks, return_exceptions=True)

    results: List[Dict[str, Any]] = []
    for pos, scan in zip(positions, scans):
        if isinstance(scan, Exception):
            logger.warning(
                "DCA: scan error for %s: %s",
                pos.get("symbol"), scan,
            )
            scan = None
        result = evaluate_dca(pos, scan if isinstance(scan, dict) else None)
        results.append(result)
    return results
