"""Position alert service — cross-reference open positions with the Miraj scan.

For each open position, this module fetches (or runs) the latest scan for that
symbol and compares the position direction (LONG/SHORT) against the scan's
QQE signals, market structure, and confluence direction. It also checks the
distance from the current mark price to the liquidation price.

Alert severities
----------------
* ``WARNING`` — a single signal conflicts with the position direction.
* ``DANGER``  — multiple signals conflict, or the confluence direction is
  squarely opposed to the position.

The service is designed to be called from both the portfolio REST endpoint
and the APScheduler background job.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.services.analysis_service import get_cached_or_none, run_scan

logger = logging.getLogger(__name__)

# ── Symbol normalisation ────────────────────────────────────────────────────


def normalize_to_scan_symbol(position_symbol: str) -> str:
    """Convert a position symbol (e.g. ``BTC/USDT:USDT``) to a yfinance ticker.

    The scan engine expects symbols like ``BTC-USD``. Exchange position
    symbols come in various formats:
      * ``BTC/USDT:USDT``  (ccxt futures)
      * ``BTC-USDT``       (dash-separated)
      * ``BTCUSDT``        (no separator)
    """
    s = position_symbol.upper().strip()
    # Strip settlement suffix (":USDT")
    s = s.split(":")[0]
    # Replace slash with dash
    s = s.replace("/", "-")
    # Strip USDT/USD quote currency → base
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


# ── Scan fetching ───────────────────────────────────────────────────────────


async def get_scan_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Return the latest scan result for *symbol* (a yfinance ticker).

    Tries the in-memory cache first (15-min TTL). If not cached, runs the
    full pipeline in a background thread. Returns ``None`` on failure.
    """
    # 1. Try in-memory cache (no I/O)
    cached = get_cached_or_none(symbol)
    if cached is not None:
        return cached

    # 2. Run the pipeline (synchronous — offload to a thread)
    try:
        result = await asyncio.to_thread(run_scan, symbol)
        return result
    except Exception as exc:
        logger.warning("Position alert: scan failed for %s: %s", symbol, exc)
        return None


# ── Alert evaluation ────────────────────────────────────────────────────────


def _is_bullish_structure(label: str) -> bool:
    """Return True if a structure label (HH/HL) is bullish."""
    return label in ("HH", "HL")


def _is_bearish_structure(label: str) -> bool:
    """Return True if a structure label (LH/LL) is bearish."""
    return label in ("LH", "LL")


def _qqe_trend(signal: Optional[Dict[str, str]]) -> str:
    """Extract the trend ('GREEN'/'RED'/'NEUTRAL') from a QQE signal dict."""
    if not isinstance(signal, dict):
        return "NEUTRAL"
    return (signal.get("trend") or "NEUTRAL").upper()


def _qqe_strength(signal: Optional[Dict[str, str]]) -> str:
    """Extract the strength ('STRONG'/'NORMAL'/'NONE') from a QQE signal dict."""
    if not isinstance(signal, dict):
        return "NONE"
    return (signal.get("strength") or "NONE").upper()


def _infer_scan_direction(scan: Dict[str, Any]) -> Optional[str]:
    """Infer the overall directional bias of a scan result.

    Counts bullish vs bearish signals across QQE (daily/4h/1h) and structure
    (weekly/daily/4h). Returns ``"LONG"``, ``"SHORT"``, or ``None`` (neutral).
    """
    bull = 0
    bear = 0

    # QQE signals
    qqe_signals = scan.get("qqe_signals") or {}
    for tf in ("daily", "4h", "1h"):
        trend = _qqe_trend(qqe_signals.get(tf))
        if trend == "GREEN":
            bull += 1
        elif trend == "RED":
            bear += 1

    # Market structure
    structure = scan.get("structure") or {}
    for tf in ("weekly", "daily", "4h"):
        tf_struct = structure.get(tf)
        if isinstance(tf_struct, dict):
            label = (tf_struct.get("label") or "").upper()
            if _is_bullish_structure(label):
                bull += 1
            elif _is_bearish_structure(label):
                bear += 1

    if bull > bear + 1:
        return "LONG"
    if bear > bull + 1:
        return "SHORT"
    return None


def evaluate_position_alerts(
    position: Dict[str, Any],
    scan: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return a list of alert dicts for a single position vs scan result.

    *position* must have keys: symbol, side, size, entry_price, mark_price,
    pnl, leverage, liquidation_price, margin.

    *scan* is the full scan result dict (may be ``None`` when the scan
    failed — only the liquidation-distance check runs in that case).

    Each alert dict has:
        type, severity ("WARNING"/"DANGER"), message, action
    """
    alerts: List[Dict[str, Any]] = []
    side = (position.get("side") or "").upper()
    is_long = side in ("LONG", "BUY")
    is_short = side in ("SHORT", "SELL")
    if not is_long and not is_short:
        return alerts
    position_dir = "LONG" if is_long else "SHORT"
    opposite_dir = "SHORT" if is_long else "LONG"

    # ── Liquidation distance check (independent of scan) ───────────
    liq_price = position.get("liquidation_price")
    mark_price = position.get("mark_price") or position.get("entry_price")
    if liq_price is not None and mark_price is not None and liq_price > 0:
        distance_pct = abs(mark_price - liq_price) / mark_price * 100.0
        if distance_pct < 2.0:
            alerts.append({
                "type": "LIQ_DISTANCE",
                "severity": "DANGER",
                "message": (
                    f"Mark price is only {distance_pct:.1f}% from liquidation "
                    f"({mark_price:.4f} → liq {liq_price:.4f}) while holding {position_dir}"
                ),
                "action": "Reduce position size or add margin immediately",
            })
        elif distance_pct < 5.0:
            alerts.append({
                "type": "LIQ_DISTANCE",
                "severity": "WARNING",
                "message": (
                    f"Mark price is {distance_pct:.1f}% from liquidation "
                    f"({mark_price:.4f} → liq {liq_price:.4f}) while holding {position_dir}"
                ),
                "action": "Monitor closely — consider tightening stop or reducing size",
            })

    if scan is None:
        return alerts

    # ── QQE signal conflicts (per timeframe) ───────────────────────
    qqe_signals = scan.get("qqe_signals") or {}
    conflicting_tfs: List[str] = []
    for tf_label, tf_key in (("Daily", "daily"), ("4H", "4h"), ("1H", "1h")):
        sig = qqe_signals.get(tf_key)
        trend = _qqe_trend(sig)
        strength = _qqe_strength(sig)
        if trend == "NEUTRAL":
            continue
        # GREEN = bullish; if holding SHORT → conflict
        # RED = bearish; if holding LONG → conflict
        conflicts = (trend == "RED" and is_long) or (trend == "GREEN" and is_short)
        if not conflicts:
            continue
        conflicting_tfs.append(tf_key)
        strength_suffix = f"-{strength}" if strength == "STRONG" else ""
        severity = "DANGER" if strength == "STRONG" else "WARNING"
        alerts.append({
            "type": "QQE_FLIP",
            "severity": severity,
            "message": (
                f"{tf_label} QQE flipped to {trend}{strength_suffix} "
                f"while holding {position_dir}"
            ),
            "action": "Consider reducing position size",
        })

    # ── Market structure conflicts ─────────────────────────────────
    structure = scan.get("structure") or {}
    for tf_label, tf_key in (("Weekly", "weekly"), ("Daily", "daily"), ("4H", "4h")):
        tf_struct = structure.get(tf_key)
        if not isinstance(tf_struct, dict):
            continue
        label = (tf_struct.get("label") or "").upper()
        if not label:
            continue
        # Bearish structure (LH/LL) + LONG → conflict
        # Bullish structure (HH/HL) + SHORT → conflict
        bearish = _is_bearish_structure(label)
        bullish = _is_bullish_structure(label)
        conflicts = (bearish and is_long) or (bullish and is_short)
        if not conflicts:
            continue
        # Daily structure conflicts are more severe than weekly/4h
        severity = "DANGER" if tf_key == "daily" else "WARNING"
        direction_word = "bearish" if bearish else "bullish"
        alerts.append({
            "type": "STRUCTURE",
            "severity": severity,
            "message": (
                f"{tf_label} market structure is {label} ({direction_word}) "
                f"while holding {position_dir}"
            ),
            "action": "Review market structure before adding to position",
        })

    # ── Confluence direction conflict (overall) ────────────────────
    scan_dir = _infer_scan_direction(scan)
    if scan_dir is not None and scan_dir == opposite_dir:
        # Count how many signals conflict to gauge severity
        conflict_count = len(conflicting_tfs)
        bearish_structs = sum(
            1 for tf in ("weekly", "daily", "4h")
            if isinstance(structure.get(tf), dict)
            and _is_bearish_structure((structure[tf].get("label") or "").upper())
        )
        bullish_structs = sum(
            1 for tf in ("weekly", "daily", "4h")
            if isinstance(structure.get(tf), dict)
            and _is_bullish_structure((structure[tf].get("label") or "").upper())
        )
        struct_conflicts = bearish_structs if is_long else bullish_structs
        total_conflicts = conflict_count + struct_conflicts
        severity = "DANGER" if total_conflicts >= 3 else "WARNING"
        alerts.append({
            "type": "CONFLUENCE",
            "severity": severity,
            "message": (
                f"Scan confluence direction is {scan_dir} but position is {position_dir} "
                f"({total_conflicts} conflicting signals)"
            ),
            "action": "Consider closing or hedging the position",
        })

    return alerts


def max_severity(alerts: List[Dict[str, Any]]) -> Optional[str]:
    """Return the highest severity among *alerts* ('DANGER' > 'WARNING')."""
    if not alerts:
        return None
    if any(a.get("severity") == "DANGER" for a in alerts):
        return "DANGER"
    return "WARNING"


async def compute_position_alerts(
    positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compute alerts for a list of open positions.

    Returns a list of dicts:
        {symbol, position_side, position_size, alerts: [...], max_severity}
    Only positions with at least one alert are included.
    """
    # Fetch scans concurrently (bounded to avoid hammering yfinance)
    semaphore = asyncio.Semaphore(3)

    async def fetch_scan(pos_symbol: str) -> Optional[Dict[str, Any]]:
        scan_symbol = normalize_to_scan_symbol(pos_symbol)
        async with semaphore:
            return await get_scan_for_symbol(scan_symbol)

    scan_tasks = [fetch_scan(p.get("symbol", "")) for p in positions]
    scans = await asyncio.gather(*scan_tasks, return_exceptions=True)

    results: List[Dict[str, Any]] = []
    for pos, scan in zip(positions, scans):
        if isinstance(scan, Exception):
            logger.warning(
                "Position alert: scan error for %s: %s",
                pos.get("symbol"), scan,
            )
            scan = None
        alerts = evaluate_position_alerts(pos, scan if isinstance(scan, dict) else None)
        if alerts:
            results.append({
                "symbol": pos.get("symbol"),
                "position_side": (pos.get("side") or "").upper(),
                "position_size": pos.get("size"),
                "max_severity": max_severity(alerts),
                "alerts": alerts,
            })
    return results
