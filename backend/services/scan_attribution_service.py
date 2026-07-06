"""Scan attribution service — link closed positions to the scans that preceded them.

For every closed position in ``PositionHistory`` this module finds the most
recent ``Analysis`` (scan) row for the same symbol whose ``created_at`` is at
or before the position's ``open_time``. It then extracts the confluence score,
the inferred trade direction, and the per-timeframe QQE signal summary so the
frontend can show *which* confluence score led to each trade.

The same linking logic powers two endpoints:

* ``GET /api/v1/portfolio/{exchange}/trade-attribution``
  (per-trade table + footer summary)
* ``GET /api/v1/analytics/{exchange}/scan-accuracy``
  (win rate / avg PnL per score band)

Symbol-format translation (e.g. ``BTC/USDT:USDT`` → ``BTC-USD``) is handled by
``position_alert_service.normalize_to_scan_symbol`` so exchange position
symbols match the yfinance tickers stored in the ``analyses`` table.
"""

from __future__ import annotations

import bisect
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Analysis, PositionHistory
from backend.services.position_alert_service import normalize_to_scan_symbol

logger = logging.getLogger(__name__)


# ── Parsing helpers (mirrors routes/scan_diff.py) ───────────────────────────


def _parse_result(raw: Optional[str]) -> Dict[str, Any]:
    """Parse the ``result`` JSON column into a dict; ``{}`` on any failure."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _extract_direction(scan_result: Dict[str, Any]) -> Optional[str]:
    """Return ``"LONG"`` / ``"SHORT"`` from a scan result, else ``None``.

    Prefers ``trade_plan_flat.direction`` (built by the analysis service),
    then falls back to ``trade_plan.direction``, then to the inferred
    confluence direction.
    """
    flat = scan_result.get("trade_plan_flat")
    if isinstance(flat, dict):
        d = flat.get("direction")
        if d:
            return str(d).upper()

    plan = scan_result.get("trade_plan")
    if isinstance(plan, dict):
        d = plan.get("direction")
        if d:
            return str(d).upper()

    return None


def _extract_score(scan_result: Dict[str, Any]) -> Optional[float]:
    """Return the confluence score from a parsed scan result, or ``None``."""
    conf = scan_result.get("confluence_score")
    if conf is None:
        return None
    try:
        return round(float(conf), 1)
    except (TypeError, ValueError):
        return None


def _extract_qqe_signals(scan_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the per-TF QQE summary dict, or ``None`` when absent."""
    sig = scan_result.get("qqe_signals")
    return sig if isinstance(sig, dict) else None


# ── Nearest-scan lookup ────────────────────────────────────────────────────


def _find_nearest_scan_before(
    scans: List[Analysis],
    open_time: Optional[Any],
) -> Optional[Analysis]:
    """Return the most recent scan whose ``created_at`` <= ``open_time``.

    *scans* must be sorted by ``created_at`` ascending (handled by the caller).
    When *open_time* is ``None`` the latest available scan is returned (best
    effort) so a position without a recorded open time is still attributed.
    """
    if not scans:
        return None
    if open_time is None:
        # No open time — fall back to the latest scan (last in the asc list).
        return scans[-1]

    # Ensure open_time is tz-naive for comparison with created_at (which is
    # stored tz-naive UTC). If open_time is aware, drop the tzinfo.
    ot = open_time
    if hasattr(ot, "tzinfo") and ot.tzinfo is not None:
        ot = ot.replace(tzinfo=None)

    # bisect on created_at timestamps; scans are ascending by created_at.
    keys = [s.created_at for s in scans]
    # rightmost index where keys[i] <= ot  →  bisect_right - 1
    idx = bisect.bisect_right(keys, ot) - 1
    if idx < 0:
        return None
    return scans[idx]


# ── Public API ──────────────────────────────────────────────────────────────


async def link_positions_to_scans(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """For each closed position, find the nearest pre-trade scan and link it.

    Returns a list of dicts (newest closed position first) with keys::

        position_symbol, position_side, entry_price, exit_price, pnl,
        open_time, close_time, close_reason, pnl_percent, leverage,
        scan_score, scan_direction, scan_qqe_signals

    Positions whose symbol has no recorded scan still appear in the list —
    their ``scan_*`` fields are ``None`` — so the table always reflects the
    full closed-position history.
    """
    # 1. Load closed positions (same ordering as the portfolio cache loader).
    pos_result = await session.execute(
        select(PositionHistory)
        .where(
            PositionHistory.user_id == user_id,
            PositionHistory.exchange == exchange,
        )
        .order_by(PositionHistory.close_time.desc().nullslast())
        .limit(limit)
    )
    positions = list(pos_result.scalars().all())
    if not positions:
        return []

    # 2. Batch-load all scan rows for the symbols we need (one query).
    # Normalise each position symbol to its yfinance ticker and de-dup.
    scan_symbols = {normalize_to_scan_symbol(p.symbol) for p in positions}
    scan_map: Dict[str, List[Analysis]] = {}
    if scan_symbols:
        an_result = await session.execute(
            select(Analysis)
            .where(
                Analysis.user_id == user_id,
                Analysis.pair.in_(scan_symbols),
                Analysis.analysis_type == "scan",
            )
            .order_by(Analysis.created_at.asc())
        )
        for a in an_result.scalars().all():
            scan_map.setdefault(a.pair, []).append(a)

    # 3. Link each position to its nearest pre-trade scan.
    items: List[Dict[str, Any]] = []
    for p in positions:
        scan_symbol = normalize_to_scan_symbol(p.symbol)
        scans_for_symbol = scan_map.get(scan_symbol, [])
        linked = _find_nearest_scan_before(scans_for_symbol, p.open_time)

        scan_score: Optional[float] = None
        scan_direction: Optional[str] = None
        scan_qqe_signals: Optional[Dict[str, Any]] = None
        if linked is not None:
            parsed = _parse_result(linked.result)
            scan_score = _extract_score(parsed)
            scan_direction = _extract_direction(parsed)
            scan_qqe_signals = _extract_qqe_signals(parsed)

        items.append(
            {
                "position_symbol": p.symbol,
                "position_side": (p.side or "").upper(),
                "entry_price": float(p.entry_price),
                "exit_price": float(p.exit_price),
                "pnl": float(p.pnl),
                "pnl_percent": float(getattr(p, "pnl_percent", 0.0) or 0.0),
                "leverage": float(getattr(p, "leverage", 1.0) or 1.0),
                "open_time": p.open_time,
                "close_time": p.close_time,
                "close_reason": getattr(p, "close_reason", None),
                "scan_score": scan_score,
                "scan_direction": scan_direction,
                "scan_qqe_signals": scan_qqe_signals,
            }
        )
    return items


# ── Score-band accuracy (for the analytics endpoint) ────────────────────────


# Confluence score range is 0–30. Bands are 5-point-wide half-open intervals:
# [0,5), [5,10), [10,15), [15,20), [20,25), [25,30].
SCORE_BANDS: List[tuple[float, float]] = [
    (0.0, 5.0),
    (5.0, 10.0),
    (10.0, 15.0),
    (15.0, 20.0),
    (20.0, 25.0),
    (25.0, 30.0),
]


def _band_label(lo: float, hi: float) -> str:
    """Render a band as ``"0-5"`` (int where possible)."""
    lo_s = str(int(lo)) if float(lo).is_integer() else str(lo)
    hi_s = str(int(hi)) if float(hi).is_integer() else str(hi)
    return f"{lo_s}-{hi_s}"


def compute_scan_accuracy(
    linked_trades: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Aggregate win rate and avg PnL per confluence-score band.

    Only trades with a non-null ``scan_score`` that falls within one of the
    predefined bands are counted. Returns one entry per band (including empty
    bands with ``total_trades: 0``) so the chart always has all 6 bars.
    """
    # Accumulators keyed by band label.
    totals: Dict[str, int] = {label: 0 for label in (_band_label(lo, hi) for lo, hi in SCORE_BANDS)}
    wins: Dict[str, int] = {label: 0 for label in totals}
    pnls: Dict[str, List[float]] = {label: [] for label in totals}
    order: List[str] = [_band_label(lo, hi) for lo, hi in SCORE_BANDS]

    for trade in linked_trades:
        score = trade.get("scan_score")
        pnl = trade.get("pnl")
        if score is None or pnl is None:
            continue
        try:
            score_f = float(score)
            pnl_f = float(pnl)
        except (TypeError, ValueError):
            continue

        for lo, hi in SCORE_BANDS:
            if lo <= score_f < hi:
                label = _band_label(lo, hi)
                totals[label] += 1
                if pnl_f > 0:
                    wins[label] += 1
                pnls[label].append(pnl_f)
                break

    result: List[Dict[str, Any]] = []
    for label in order:
        total = totals[label]
        winning = wins[label]
        win_rate = (winning / total * 100.0) if total > 0 else 0.0
        band_pnls = pnls[label]
        avg_pnl = (sum(band_pnls) / len(band_pnls)) if band_pnls else 0.0
        result.append(
            {
                "score_band": label,
                "total_trades": total,
                "winning_trades": winning,
                "win_rate": round(win_rate, 1),
                "avg_pnl": round(avg_pnl, 2),
            }
        )
    return result
