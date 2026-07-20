"""Position Desk — the portfolio page's decision layer.

For every open position: join the position facts with the typed scan
verdict (``mirai_core.verdict``), the DCA engine's recommendation, and a
one-line mechanical ruling in the app's verdict voice ("Reduce — wrong
side of the weekly band."). The ruling is composed from the same hard
rules the engines already enforce — it makes no new claims.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.services.dca_service import (
    _normalize_symbol,
    evaluate_dca,
    fetch_scans_for_positions,
)

logger = logging.getLogger(__name__)


def _liq_distance_pct(position: Dict[str, Any]) -> Optional[float]:
    liq = position.get("liquidation_price")
    mark = position.get("mark_price")
    if not liq or not mark or liq <= 0 or mark <= 0:
        return None
    return round(abs(mark - liq) / mark * 100.0, 2)


def _fmt_price(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 1:
        return f"{value:,.2f}"
    return f"{value:.4f}"


def _alignment(side: str, scan: Optional[Dict[str, Any]]) -> str:
    """Position side vs the weekly BMSB regime — the methodology's big gate."""
    if scan is None:
        return "NO_DATA"
    if side not in ("long", "short"):
        return "MIXED"
    regime = ((scan.get("bmsb") or {}).get("regime") or "").lower()
    if regime not in ("bull", "bear"):
        return "MIXED"
    with_regime = regime == ("bull" if side == "long" else "bear")
    return "ALIGNED" if with_regime else "COUNTER_REGIME"


def _compose_ruling(
    side: str,
    recommendation: str,
    dca: Dict[str, Any],
    scan: Optional[Dict[str, Any]],
) -> str:
    """One short sentence in the verdict voice; the DCA reason stays in detail."""
    if scan is None:
        return "No data — manual review."
    if recommendation == "CLOSE":
        return "Close the position."

    regime = ((scan.get("bmsb") or {}).get("regime") or "").lower()
    against_regime = (regime == "bear" and side == "long") or (
        regime == "bull" and side == "short"
    )
    reason = dca.get("reason") or ""

    if recommendation == "REDUCE":
        if against_regime:
            return "Reduce — wrong side of the weekly band."
        # evaluate_dca's own stable reason strings discriminate the branch.
        if reason.startswith("Position up"):
            return "Reduce — withdraw initial capital."
        if reason.startswith("Price at TP1"):
            return "Reduce — take profit at TP1."
        return "Reduce — momentum flipped against."

    zone = dca.get("dca_zone") or {}
    zone_label = (
        f"{_fmt_price(zone.get('low'))}–{_fmt_price(zone.get('high'))}"
        if isinstance(zone.get("low"), (int, float))
        and isinstance(zone.get("high"), (int, float))
        else None
    )

    if recommendation == "ADD":
        return f"Add only in {zone_label}." if zone_label else "Add — conditions met."

    # HOLD
    if against_regime:
        return "Hold. No adds against the regime."
    if zone_label:
        return f"Hold. Add only in {zone_label}."
    return "Hold. No valid add zone — wait."


def build_desk_row(
    position: Dict[str, Any], scan: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Join one position with its scan into a desk row (pure, testable)."""
    raw_side = (position.get("side") or "").lower()
    side = (
        "long"
        if raw_side in ("long", "buy")
        else "short"
        if raw_side in ("short", "sell")
        else raw_side or "unknown"
    )

    dca = evaluate_dca(position, scan)
    recommendation = dca.get("recommendation", "HOLD")
    verdict = scan.get("verdict") if isinstance(scan, dict) else None
    bmsb = (scan.get("bmsb") or {}) if isinstance(scan, dict) else {}
    band_vals = [
        v
        for v in (bmsb.get("sma_20w"), bmsb.get("ema_21w"))
        if isinstance(v, (int, float))
    ]

    return {
        "symbol": position.get("symbol") or "",
        "scan_symbol": _normalize_symbol(position.get("symbol") or ""),
        "side": side,
        "size": position.get("size"),
        "entry_price": position.get("entry_price"),
        "mark_price": position.get("mark_price"),
        "pnl": position.get("pnl"),
        "pnl_percent": position.get("pnl_percent"),
        "leverage": position.get("leverage"),
        "liquidation_price": position.get("liquidation_price"),
        "liq_distance_pct": _liq_distance_pct(position),
        "verdict": verdict if isinstance(verdict, dict) else None,
        "regime": (bmsb.get("regime") or None),
        "regime_band_low": min(band_vals) if band_vals else None,
        "regime_band_high": max(band_vals) if band_vals else None,
        "alignment": _alignment(side, scan),
        "recommendation": recommendation,
        "confidence": dca.get("confidence"),
        "ruling": _compose_ruling(side, recommendation, dca, scan),
        "detail": dca.get("reason") or None,
        "add_zone": dca.get("dca_zone"),
        "next_entry": dca.get("next_entry"),
        "tp_levels": dca.get("tp_levels") or [],
        "action_items": [a for a in (dca.get("action_items") or []) if a],
        "next_review": (verdict or {}).get("next_review") if isinstance(verdict, dict) else None,
    }


async def compute_position_desk(
    positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """One desk row per open position (single concurrent scan pass)."""
    scans = await fetch_scans_for_positions(positions)
    return [build_desk_row(pos, scan) for pos, scan in zip(positions, scans)]
