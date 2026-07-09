"""Dynamic DCA service — position-aware Dollar Cost Averaging engine.

For each open position, fetches (or runs) the latest Miraj pair analysis and
computes a DCA recommendation: ADD / HOLD / REDUCE / CLOSE.

Follows Miraj's exact rules from the Meerutrades vault:
  * RSI three-entry: 20%@RSI30, 20%@RSI24, 60%@RSI16-18 (longs)
  * DCA only into valid zones (confluence >= 10)
  * QQE must confirm before adding
  * BB squeezing = don't add
  * When investment doubles -> withdraw initial capital
  * Zone-based DCA (OTE/demand zone) takes priority over RSI for swing trades
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.services.analysis_service import get_cached_or_none, run_scan

logger = logging.getLogger(__name__)

# ── Miraj constants ──────────────────────────────────────────────────────────

RSI_ENTRY_THRESHOLDS_LONG = (30, 24, 16)
RSI_ENTRY_THRESHOLDS_SHORT = (80, 92, 95)
RSI_ENTRY_ALLOCATIONS = (0.20, 0.20, 0.60)
SCORE_TRADE_THRESHOLD = 10


# ── Symbol normalisation ─────────────────────────────────────────────────────


def _normalize_symbol(position_symbol: str) -> str:
    """Convert position symbol (BTC/USDT:USDT) to yfinance ticker (BTC-USD)."""
    s = position_symbol.upper().strip()
    s = s.split(":")[0]           # strip settlement suffix
    s = s.replace("/", "-")       # slash to dash
    if s.endswith("-USDT"):
        base = s[:-5]
    elif s.endswith("-USD"):
        base = s[:-4]
    elif s.endswith("USDT") and len(s) > 4:
        base = s[:-4]
    elif s.endswith("USD") and len(s) > 3:
        base = s[:-3]
    else:
        base = s
    return f"{base}-USD" if base else s


# ── Data extraction helpers ─────────────────────────────────────────────────


def _rsi(scan: Dict[str, Any], tf: str = "daily") -> Optional[float]:
    ind = scan.get("indicators") or {}
    data = ind.get(tf) or {}
    v = data.get("rsi")
    return float(v) if isinstance(v, (int, float)) else None


def _qqe_trends(scan: Dict[str, Any]) -> Dict[str, str]:
    qqe = scan.get("qqe_signals") or {}
    out: Dict[str, str] = {}
    for tf in ("daily", "4h", "1h"):
        sig = qqe.get(tf)
        if isinstance(sig, dict):
            out[tf] = (sig.get("trend") or "NEUTRAL").upper()
        else:
            out[tf] = "NEUTRAL"
    return out


def _structure_labels(scan: Dict[str, Any]) -> Dict[str, str]:
    structure = scan.get("structure") or {}
    out: Dict[str, str] = {}
    for tf in ("weekly", "daily", "4h", "1h", "15m"):
        ts = structure.get(tf)
        if isinstance(ts, dict):
            out[tf] = (ts.get("label") or "").upper()
        else:
            out[tf] = ""
    return out


def _bb_squeeze_any(scan: Dict[str, Any]) -> bool:
    ind = scan.get("indicators") or {}
    for tf in ("daily", "4h", "1h"):
        if (ind.get(tf) or {}).get("bb_squeeze"):
            return True
    return False


def _ote_zone(scan: Dict[str, Any]) -> Optional[tuple[float, float]]:
    tp = scan.get("trade_plan") or {}
    ez = tp.get("entry_zone") or {}
    lo, hi = ez.get("low"), ez.get("high")
    if lo is not None and hi is not None:
        return float(lo), float(hi)
    return None


def _score(scan: Dict[str, Any]) -> float:
    return float(scan.get("confluence_score") or 0)


def _scan_direction(scan: Dict[str, Any]) -> Optional[str]:
    tp = scan.get("trade_plan") or {}
    d = tp.get("direction")
    return str(d).upper() if d else None


def _tp_levels(scan: Dict[str, Any]) -> List[float]:
    tp = scan.get("trade_plan") or {}
    targets = tp.get("take_profit_targets") or []
    out: List[float] = []
    if isinstance(targets, list):
        for t in targets[:3]:
            lvl = t.get("level") if isinstance(t, dict) else None
            if lvl is not None:
                out.append(float(lvl))
    return out


def _patterns(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    p = scan.get("patterns")
    if not isinstance(p, dict):
        return []
    out: List[Dict[str, Any]] = []
    for key in ("daily", "4h", "1h"):
        items = p.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    out.append(item)
        elif isinstance(items, dict):
            out.append(items)
    return out


def _bmsb(scan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    b = scan.get("bmsb")
    if isinstance(b, dict) and b.get("current_price"):
        return b
    return None


# ── Adaptive RSI entry ladder ───────────────────────────────────────────────


def _compute_entries(
    direction: str,
    rsi_current: Optional[float],
    ote: Optional[tuple[float, float]],
) -> List[Dict[str, Any]]:
    """Build the Miraj three-entry ladder, marking filled / pending."""
    is_long = direction == "LONG"
    thresholds = RSI_ENTRY_THRESHOLDS_LONG if is_long else RSI_ENTRY_THRESHOLDS_SHORT
    entries: List[Dict[str, Any]] = []
    cumulative = 0.0

    for i, (thresh, alloc) in enumerate(zip(thresholds, RSI_ENTRY_ALLOCATIONS)):
        if rsi_current is not None:
            reached = rsi_current <= thresh if is_long else rsi_current >= thresh
        else:
            reached = False
        cumulative += alloc
        entries.append(
            {
                "entry": f"Entry {i + 1}",
                "trigger": f"RSI hits {thresh}",
                "position_size_pct": f"{alloc * 100:.0f}%",
                "cumulative_pct": f"{min(cumulative, 1.0) * 100:.0f}%",
                "status": "filled" if reached else "pending",
                "trigger_type": "rsi",
                "rsi_target": thresh,
                "level_price": ote[0] if (ote and is_long) else (ote[1] if ote else None),
            }
        )
    return entries


def _next_entry(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in entries:
        if e["status"] == "pending":
            return e
    return None


# ── Core evaluation ─────────────────────────────────────────────────────────


def evaluate_dca(
    position: Dict[str, Any],
    scan: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate a single open position against the scan and return a recommendation."""
    side = (position.get("side") or "").upper()
    is_long = side in ("LONG", "BUY")
    is_short = side in ("SHORT", "SELL")
    direction = "LONG" if is_long else "SHORT" if is_short else "NEUTRAL"

    result: Dict[str, Any] = {
        "symbol": position.get("symbol"),
        "position_side": side,
        "entry_price": position.get("entry_price") or 0,
        "mark_price": position.get("mark_price") or 0,
        "pnl": position.get("pnl") or 0,
        "pnl_percent": position.get("pnl_percent") or 0,
        "leverage": position.get("leverage") or 1,
        "recommendation": "HOLD",
        "reason": "",
        "confidence": "LOW",
        "rsi_current": None,
        "rsi_entries": [],
        "next_entry": None,
        "dca_zone": None,
        "tp_levels": [],
        "risk_rules": [],
        "future_add_triggers": [],
        "action_items": [],
    }

    if not is_long and not is_short:
        result["reason"] = "Unknown position side."
        return result

    # ── Risk rules (always returned) ─────────────────────────────────
    result["risk_rules"] = [
        "Risk 0.5-1% of portfolio per trade",
        "When investment DOUBLES → withdraw initial capital",
        "Use DCA — split entries, don't enter full position at once",
        "Wait for candle CLOSE confirmation",
    ]

    entry_price = float(result["entry_price"])
    mark_price = float(result["mark_price"]) or entry_price
    pnl_pct = float(result["pnl_percent"] or 0)

    # ── Liquidation check ────────────────────────────────────────────
    liq_price = position.get("liquidation_price")
    if liq_price and mark_price and liq_price > 0:
        liq_dist = abs(mark_price - liq_price) / mark_price * 100
        if liq_dist < 2:
            result["recommendation"] = "CLOSE"
            result["confidence"] = "CRITICAL"
            result["reason"] = f"Mark price only {liq_dist:.1f}% from liquidation. Exit immediately."
            result["action_items"] = ["Close entire position now — liquidation imminent"]
            return result

    if scan is None:
        result["reason"] = "Scan unavailable — cannot compute DCA levels."
        return result

    # ── Extract scan data ────────────────────────────────────────────
    rsi = _rsi(scan)
    rsi_4h = _rsi(scan, "4h")
    qqe = _qqe_trends(scan)
    structure = _structure_labels(scan)
    bb_sq = _bb_squeeze_any(scan)
    ote = _ote_zone(scan)
    score = _score(scan)
    scan_dir = _scan_direction(scan)
    tps = _tp_levels(scan)
    patterns = _patterns(scan)
    bmsb = _bmsb(scan)

    result["rsi_current"] = rsi
    result["tp_levels"] = tps
    result["rsi_entries"] = _compute_entries(direction, rsi, ote)
    result["next_entry"] = _next_entry(result["rsi_entries"])

    if ote:
        result["dca_zone"] = {"low": ote[0], "high": ote[1], "label": f"OTE {ote[0]:.2f}-{ote[1]:.2f}"}

    # ── Confirmed opposite pattern? ──────────────────────────────────
    opposite_pattern = False
    pattern_name = ""
    for p in patterns:
        pdir = (p.get("direction") or "").upper()
        pname = p.get("name") or p.get("pattern") or ""
        confirmed = p.get("confirmed", True)
        if not confirmed:
            continue
        if (is_long and pdir == "BEARISH") or (is_short and pdir == "BULLISH"):
            opposite_pattern = True
            pattern_name = pname
            break

    # ── STEP 1: PnL >= 100% → withdraw initial capital ─────────────
    if pnl_pct >= 100:
        result["recommendation"] = "REDUCE"
        result["confidence"] = "HIGH"
        result["reason"] = f"Position up {pnl_pct:.1f}%. Miraj rule: withdraw initial capital, trade with house money."
        result["action_items"] = ["Withdraw initial capital", "Keep remaining position with stop at breakeven"]
        return result

    # ── STEP 2: Price at/near TP1 → take partial profit ─────────────
    if tps and mark_price:
        tp1 = tps[0]
        dist_to_tp1 = abs(mark_price - tp1) / tp1 * 100
        if dist_to_tp1 < 2 and mark_price >= tp1 * 0.98:
            result["recommendation"] = "REDUCE"
            result["confidence"] = "HIGH"
            result["reason"] = f"Price at TP1 (${tp1:.2f}). Take 50% profit. Move stop to breakeven."
            result["action_items"] = [
                f"Close 50% of position at ~${mark_price:.2f} (TP1 hit)",
                "Move stop to breakeven (entry price)",
                f"Keep remaining 50% targeting TP2: ${tps[1]:.2f}" if len(tps) > 1 else "",
            ]
            # continue evaluating — TP1 is partial exit, not full close
            result["future_add_triggers"] = [
                "4H QQE must turn GREEN" if (qqe.get("4h") == "RED" and is_long) else "",
                f"Price must pull back to OTE zone ${ote[0]:.2f}-${ote[1]:.2f}" if ote else "",
            ]
            result["future_add_triggers"] = [t for t in result["future_add_triggers"] if t]
            return result

    # ── STEP 3: Confluence direction opposed with 3+ conflicts → CLOSE
    conflict_count = 0
    for tf in ("daily", "4h", "1h"):
        trend = qqe.get(tf, "NEUTRAL")
        if (trend == "RED" and is_long) or (trend == "GREEN" and is_short):
            conflict_count += 1
    for tf in ("weekly", "daily", "4h"):
        label = structure.get(tf, "")
        if (label in ("LH", "LL") and is_long) or (label in ("HH", "HL") and is_short):
            conflict_count += 1

    if scan_dir and scan_dir != direction and scan_dir != "NEUTRAL" and conflict_count >= 3:
        result["recommendation"] = "CLOSE"
        result["confidence"] = "CRITICAL"
        result["reason"] = f"Scan direction {scan_dir} vs position {direction} ({conflict_count} conflicts). Exit."
        result["action_items"] = ["Close entire position — market reversed"]
        return result

    # ── STEP 4: BMSB below + LONG → REDUCE ────────────────────────
    if bmsb and is_long:
        bmsb_status = (bmsb.get("status") or "").lower()
        if bmsb_status == "below":
            result["recommendation"] = "REDUCE"
            result["confidence"] = "HIGH"
            sma = bmsb.get("sma_20w")
            ema = bmsb.get("ema_21w")
            band_val = sma or ema
            result["reason"] = (
                f"Below BMSB ({'bear regime' if bmsb_status == 'below' else 'bull regime'}). "
                f"Miraj: avoid longs below BMSB."
            )
            if band_val:
                result["future_add_triggers"].append(f"Price must reclaim BMSB ${band_val:.2f} to re-enter bull regime")
            result["action_items"] = [
                "Reduce position size — bear market regime",
                f"Move stop to recent 4H swing low",
            ]
            return result

    # ── STEP 5: QQE both Daily+4H against → REDUCE ─────────────────
    qqe_d = qqe.get("daily", "NEUTRAL")
    qqe_4 = qqe.get("4h", "NEUTRAL")
    d_against = (qqe_d == "RED" and is_long) or (qqe_d == "GREEN" and is_short)
    f_against = (qqe_4 == "RED" and is_long) or (qqe_4 == "GREEN" and is_short)

    if d_against and f_against:
        result["recommendation"] = "REDUCE"
        result["confidence"] = "HIGH"
        result["reason"] = f"QQE flipped against on Daily ({qqe_d}) + 4H ({qqe_4}). Momentum gone."
        result["action_items"] = ["Reduce 50% of position", "Move stop tighter"]
        result["future_add_triggers"] = [
            "Daily QQE must turn GREEN" if d_against else "",
            "4H QQE must turn GREEN" if f_against else "",
        ]
        result["future_add_triggers"] = [t for t in result["future_add_triggers"] if t]
        return result

    # ── STEP 6: DCA disabled conditions → HOLD ──────────────────────
    if bb_sq:
        result["recommendation"] = "HOLD"
        result["confidence"] = "MEDIUM"
        result["reason"] = "BB squeezing — direction unclear. Miraj: don't add until squeeze resolves."
        return result

    # QQE aligned on at least one TF?
    qqe_aligned = any(
        (qqe.get(tf) == "GREEN" and is_long) or (qqe.get(tf) == "RED" and is_short)
        for tf in ("daily", "4h", "1h")
    )

    if not qqe_aligned:
        result["recommendation"] = "HOLD"
        result["confidence"] = "MEDIUM"
        result["reason"] = f"QQE not aligned with {direction} on any timeframe. Wait for confirmation."
        result["future_add_triggers"] = [
            f"{'Daily' if not d_against else '4H'} QQE must turn {'GREEN' if is_long else 'RED'}"
        ]
        return result

    if score < SCORE_TRADE_THRESHOLD:
        result["recommendation"] = "HOLD"
        result["confidence"] = "MEDIUM"
        result["reason"] = f"Confluence {score:.1f}/30 < {SCORE_TRADE_THRESHOLD}. Not enough confirmation to add."
        return result

    if opposite_pattern:
        result["recommendation"] = "HOLD"
        result["confidence"] = "HIGH"
        result["reason"] = f"{pattern_name} confirmed (bearish). Wait for pattern to invalidate before adding."
        result["future_add_triggers"].append(f"{pattern_name} pattern must invalidate")
        return result

    # ── STEP 7: Zone-based ADD ──────────────────────────────────────
    price_in_ote = False
    if ote and mark_price:
        price_in_ote = ote[0] <= mark_price <= ote[1]

    rsi_oversold = False
    if rsi is not None:
        rsi_oversold = rsi <= 35 if is_long else rsi >= 65

    if price_in_ote and qqe_aligned and rsi_oversold:
        nxt = result["next_entry"]
        nxt_label = nxt["entry"] if nxt else "next entry"
        nxt_size = nxt["position_size_pct"] if nxt else "—"
        result["recommendation"] = "ADD"
        result["confidence"] = "HIGH"
        result["reason"] = (
            f"Price in OTE zone + QQE aligned + RSI {rsi:.1f} oversold. "
            f"Deploy {nxt_size} at {nxt_label}."
        )
        result["action_items"] = [f"Deploy {nxt_size} at {nxt_label} — all conditions met"]
    elif price_in_ote and qqe_aligned:
        nxt = result["next_entry"]
        nxt_size = nxt["position_size_pct"] if nxt else "—"
        result["recommendation"] = "ADD"
        result["confidence"] = "MEDIUM"
        result["reason"] = (
            f"Price in OTE zone + QQE aligned. RSI {rsi:.1f} not deeply oversold but zone is valid. "
            f"Deploy {nxt_size}."
        )
        result["action_items"] = [f"Deploy {nxt_size} — zone valid despite RSI"]
    elif rsi_oversold and not price_in_ote:
        result["recommendation"] = "HOLD"
        result["confidence"] = "MEDIUM"
        result["reason"] = (
            f"RSI {rsi:.1f} oversold but price not in OTE zone. Wait for price to reach demand zone."
        )
        if ote:
            result["future_add_triggers"].append(
                f"Price must pull back to OTE zone ${ote[0]:.2f}-${ote[1]:.2f}"
            )
    else:
        result["recommendation"] = "HOLD"
        result["confidence"] = "LOW"
        rsi_str = f"{rsi:.1f}" if rsi else "N/A"
        result["reason"] = (
            f"QQE aligned but RSI {rsi_str} not in oversold zone and price not in OTE. "
            "Wait for pullback."
        )
        if ote:
            result["future_add_triggers"].append(
                f"Price must pull back to OTE zone ${ote[0]:.2f}-${ote[1]:.2f}"
            )
        result["future_add_triggers"].append(
            f"RSI must drop below 30 (currently {rsi:.1f})" if rsi else "RSI must drop below 30"
        )

    return result


# ── Batch computation ────────────────────────────────────────────────────────


async def compute_dca_recommendations(
    positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compute DCA for all open positions (concurrent scan fetching)."""
    semaphore = asyncio.Semaphore(3)

    async def _fetch(pos_symbol: str) -> Optional[Dict[str, Any]]:
        sym = _normalize_symbol(pos_symbol)
        cached = get_cached_or_none(sym)
        if cached is not None:
            return cached
        try:
            async with semaphore:
                return await asyncio.to_thread(run_scan, sym)
        except Exception as exc:
            logger.warning("DCA scan failed for %s: %s", sym, exc)
            return None

    scans = await asyncio.gather(
        *[_fetch(p.get("symbol", "")) for p in positions],
        return_exceptions=True,
    )

    results: List[Dict[str, Any]] = []
    for pos, scan in zip(positions, scans):
        if isinstance(scan, Exception):
            scan = None
        results.append(evaluate_dca(pos, scan if isinstance(scan, dict) else None))
    return results
