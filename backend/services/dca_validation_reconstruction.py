"""DCA validation scan-history reconstruction service.

This module reconstructs DCA recommendation/fill events from stored
``Analysis.result`` scan rows. It intentionally uses only persisted scan fields
and explicit portfolio position context; missing scan fields produce skipped
scan reasons rather than invented data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Analysis, PortfolioPosition
from backend.services.dca_service import (
    RSI_ENTRY_ALLOCATIONS,
    RSI_ENTRY_THRESHOLDS_LONG,
    RSI_ENTRY_THRESHOLDS_SHORT,
)

METHOD_LABEL = "scan-to-scan"
METHOD_DESCRIPTION = "scan-history reconstruction; not candle-level historical replay"
MIN_USABLE_SCANS = 2
SCAN_GAP_WARNING_SECONDS = 48 * 60 * 60
SLIPPAGE_RATE = 0.0005
FEE_RATE = 0.0004


@dataclass(frozen=True)
class UsableScan:
    timestamp: datetime
    result: dict[str, Any]
    direction: str
    rsi: float
    mark_price: float
    reason: str
    confidence: Any


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat()


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_rsi(result: dict[str, Any]) -> float | None:
    indicators = result.get("indicators")
    if isinstance(indicators, dict):
        daily = indicators.get("daily")
        if isinstance(daily, dict):
            value = _to_float(daily.get("rsi"))
            if value is not None:
                return value
    return _to_float(result.get("rsi"))


def _extract_mark_price(result: dict[str, Any]) -> float | None:
    for key in ("mark_price", "current_price"):
        value = _to_float(result.get(key))
        if value is not None:
            return value
    bmsb = result.get("bmsb")
    if isinstance(bmsb, dict):
        return _to_float(bmsb.get("current_price"))
    return None


def _parse_result(raw: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not raw:
        return None, "malformed_scan_result"
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None, "malformed_scan_result"
    if not isinstance(parsed, dict):
        return None, "malformed_scan_result"
    return parsed, None


def _parse_parameters(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _position_direction(position: PortfolioPosition | None) -> str | None:
    if position is None:
        return None
    side = str(position.side or "").upper()
    if side in {"LONG", "BUY"}:
        return "LONG"
    if side in {"SHORT", "SELL"}:
        return "SHORT"
    return None


def _skip(timestamp: datetime, reason: str) -> dict[str, Any]:
    return {"timestamp": _iso(timestamp), "reason": reason}


def _validate_scan(
    row: Analysis,
    position: PortfolioPosition | None,
) -> tuple[UsableScan | None, dict[str, Any] | None]:
    result, parse_error = _parse_result(row.result)
    if parse_error:
        return None, _skip(row.created_at, parse_error)

    if position is None or _position_direction(position) is None:
        return None, _skip(row.created_at, "missing_position_context")

    trade_plan = result.get("trade_plan")
    if not isinstance(trade_plan, dict):
        return None, _skip(row.created_at, "missing_trade_plan")

    raw_direction = trade_plan.get("direction")
    direction = str(raw_direction).upper() if raw_direction is not None else ""
    if direction not in {"LONG", "SHORT"}:
        return None, _skip(row.created_at, "unsupported_direction")

    rsi = _extract_rsi(result)
    if rsi is None:
        return None, _skip(row.created_at, "missing_rsi")

    mark_price = _extract_mark_price(result)
    if mark_price is None:
        return None, _skip(row.created_at, "missing_mark_price")

    return (
        UsableScan(
            timestamp=row.created_at,
            result=result,
            direction=direction,
            rsi=rsi,
            mark_price=mark_price,
            reason=str(trade_plan.get("reasoning") or trade_plan.get("verdict") or ""),
            confidence=result.get("confidence") or result.get("confluence_score"),
        ),
        None,
    )


def _fill_assumptions() -> dict[str, Any]:
    return {
        "long_thresholds": list(RSI_ENTRY_THRESHOLDS_LONG),
        "short_thresholds": list(RSI_ENTRY_THRESHOLDS_SHORT),
        "allocations": [int(round(value * 100)) for value in RSI_ENTRY_ALLOCATIONS],
        "slippage_percent": SLIPPAGE_RATE * 100,
        "fee_percent": FEE_RATE * 100,
    }


def _crossed(direction: str, previous_rsi: float, current_rsi: float, threshold: float) -> bool:
    if direction == "LONG":
        return previous_rsi > threshold >= current_rsi
    return previous_rsi < threshold <= current_rsi


def _entry_fill_price(direction: str, raw_price: float) -> float:
    return raw_price * (1 + SLIPPAGE_RATE) if direction == "LONG" else raw_price * (1 - SLIPPAGE_RATE)


def _exit_fill_price(direction: str, raw_price: float) -> float:
    return raw_price * (1 - SLIPPAGE_RATE) if direction == "LONG" else raw_price * (1 + SLIPPAGE_RATE)


def _raw_pnl(direction: str, quantity: float, entry_price: float, valuation_price: float) -> float:
    if direction == "LONG":
        return quantity * (valuation_price - entry_price)
    return quantity * (entry_price - valuation_price)


def _simulate_events(
    scans: list[UsableScan],
    position: PortfolioPosition,
    max_gap_seconds: int | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    direction = _position_direction(position)
    if direction not in {"LONG", "SHORT"} or len(scans) < MIN_USABLE_SCANS:
        return [], None, None

    thresholds = RSI_ENTRY_THRESHOLDS_LONG if direction == "LONG" else RSI_ENTRY_THRESHOLDS_SHORT
    base_notional = float(position.margin or 0) or abs(float(position.size or 0) * float(position.entry_price or 0))
    events: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    filled_levels: set[int] = set()
    close_scan: UsableScan | None = None

    for previous, current in zip(scans, scans[1:]):
        gap_seconds = int((current.timestamp - previous.timestamp).total_seconds())
        gap_assumption = "assumed_scan_gap_over_48h" if gap_seconds > SCAN_GAP_WARNING_SECONDS else "confirmed_scan_to_scan"

        if fills and current.direction != direction:
            close_scan = current
            events.append(
                {
                    "timestamp": _iso(current.timestamp),
                    "symbol": str(position.symbol),
                    "recommendation": "CLOSE",
                    "confidence": current.confidence,
                    "reason": current.reason or f"Scan direction {current.direction} opposed position {direction}",
                    "participates_in_metrics": True,
                    "method": METHOD_LABEL,
                }
            )
            break

        if current.direction != direction:
            events.append(
                {
                    "timestamp": _iso(current.timestamp),
                    "symbol": str(position.symbol),
                    "recommendation": "HOLD",
                    "confidence": current.confidence,
                    "reason": f"Scan direction {current.direction} does not match position {direction}; no filled DCA entries to close",
                    "participates_in_metrics": False,
                    "method": METHOD_LABEL,
                }
            )
            continue

        crossed_level = None
        for level, threshold in enumerate(thresholds, start=1):
            if level in filled_levels:
                continue
            if _crossed(direction, previous.rsi, current.rsi, threshold):
                crossed_level = (level, threshold)
                break

        if crossed_level is None:
            events.append(
                {
                    "timestamp": _iso(current.timestamp),
                    "symbol": str(position.symbol),
                    "recommendation": "HOLD",
                    "confidence": current.confidence,
                    "reason": current.reason or "No new DCA RSI threshold crossed",
                    "participates_in_metrics": False,
                    "method": METHOD_LABEL,
                }
            )
            continue

        level, threshold = crossed_level
        filled_levels.add(level)
        allocation = RSI_ENTRY_ALLOCATIONS[level - 1]
        notional = base_notional * allocation
        quantity = notional / current.mark_price if current.mark_price else 0.0
        fee = notional * FEE_RATE
        slippage_impact = notional * SLIPPAGE_RATE
        fill = {
            "level": level,
            "threshold": threshold,
            "allocation_percent": int(round(allocation * 100)),
            "timestamp": _iso(current.timestamp),
            "raw_price": current.mark_price,
            "fill_price": _entry_fill_price(direction, current.mark_price),
            "notional": notional,
            "quantity": quantity,
            "fee": fee,
            "slippage_impact": slippage_impact,
            "fill_assumption": gap_assumption,
        }
        fills.append(fill)
        events.append(
            {
                "timestamp": _iso(current.timestamp),
                "symbol": str(position.symbol),
                "recommendation": "ADD",
                "confidence": current.confidence,
                "reason": current.reason or f"RSI crossed {threshold}",
                "participates_in_metrics": True,
                "method": METHOD_LABEL,
                "entry_level": level,
                "rsi_threshold": threshold,
                "allocation_percent": int(round(allocation * 100)),
                "raw_price": current.mark_price,
                "fill_price": fill["fill_price"],
                "fee": fee,
                "slippage_impact": slippage_impact,
                "fill_assumption": gap_assumption,
            }
        )

    if not fills:
        return events, {"status": "open", "fills": []}, {
            "gross_pnl": 0.0,
            "fees": 0.0,
            "slippage_impact": 0.0,
            "net_pnl": 0.0,
        }

    valuation_scan = close_scan or scans[-1]
    exit_raw_notional = sum(fill["quantity"] * valuation_scan.mark_price for fill in fills)
    exit_fee = exit_raw_notional * FEE_RATE
    exit_slippage = exit_raw_notional * SLIPPAGE_RATE
    gross_pnl = sum(
        _raw_pnl(direction, fill["quantity"], fill["raw_price"], valuation_scan.mark_price)
        for fill in fills
    )
    entry_fees = sum(fill["fee"] for fill in fills)
    entry_slippage = sum(fill["slippage_impact"] for fill in fills)
    total_fees = entry_fees + exit_fee
    total_slippage = entry_slippage + exit_slippage
    pnl = {
        "gross_pnl": round(gross_pnl, 2),
        "fees": round(total_fees, 2),
        "slippage_impact": round(total_slippage, 2),
        "net_pnl": round(gross_pnl - total_fees - total_slippage, 2),
    }
    reconstructed_position: dict[str, Any] = {
        "status": "closed" if close_scan else "open",
        "direction": direction,
        "fills": fills,
        "valuation_price": valuation_scan.mark_price,
        "valuation_timestamp": _iso(valuation_scan.timestamp),
        "exit_price": _exit_fill_price(direction, valuation_scan.mark_price),
    }
    if close_scan:
        reconstructed_position["exit_timestamp"] = _iso(close_scan.timestamp)
        reconstructed_position["exit_signal"] = "CLOSE"

    return events, reconstructed_position, pnl


async def _load_positions(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: str | None,
) -> dict[str, PortfolioPosition]:
    stmt = select(PortfolioPosition).where(
        PortfolioPosition.user_id == user_id,
        PortfolioPosition.exchange == exchange,
    )
    if symbol:
        stmt = stmt.where(PortfolioPosition.symbol == symbol)
    result = await session.execute(stmt)
    return {str(row.symbol): row for row in result.scalars().all()}


async def _load_analyses(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: str | None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[Analysis]:
    stmt = (
        select(Analysis)
        .where(
            Analysis.user_id == user_id,
            Analysis.analysis_type.in_(["scan", "deep_scan", "scheduled_scan"]),
        )
        .order_by(Analysis.pair.asc(), Analysis.created_at.asc(), Analysis.id.asc())
    )
    if symbol:
        stmt = stmt.where(Analysis.pair == symbol)
    if start_date:
        stmt = stmt.where(Analysis.created_at >= start_date)
    if end_date:
        stmt = stmt.where(Analysis.created_at <= end_date)
    result = await session.execute(stmt)
    rows: list[Analysis] = []
    for row in result.scalars().all():
        params = _parse_parameters(row.parameters)
        row_exchange = params.get("exchange")
        if row_exchange is not None and row_exchange != exchange:
            continue
        rows.append(row)
    return rows


def _coverage_for_symbol(
    symbol: str,
    rows: list[Analysis],
    position: PortfolioPosition | None,
) -> dict[str, Any]:
    usable: list[UsableScan] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        scan, skip = _validate_scan(row, position)
        if skip:
            skipped.append(skip)
        elif scan:
            usable.append(scan)

    usable.sort(key=lambda scan: scan.timestamp)
    gaps = [
        int((current.timestamp - previous.timestamp).total_seconds())
        for previous, current in zip(usable, usable[1:])
    ]
    max_gap = max(gaps) if gaps else None
    warnings = ["scan_gap_over_48_hours"] if max_gap and max_gap > SCAN_GAP_WARNING_SECONDS else []
    events, reconstructed_position, pnl = _simulate_events(usable, position, max_gap) if position else ([], None, None)
    status = "metrics_available" if len(usable) >= MIN_USABLE_SCANS else "insufficient_history"

    return {
        "symbol": symbol,
        "status": status,
        "required_minimum_scans": MIN_USABLE_SCANS,
        "scan_count": len(usable),
        "first_scan_at": _iso(usable[0].timestamp) if usable else None,
        "last_scan_at": _iso(usable[-1].timestamp) if usable else None,
        "max_scan_gap_seconds": max_gap,
        "method": METHOD_LABEL,
        "method_description": METHOD_DESCRIPTION,
        "events": events if status == "metrics_available" else [],
        "reconstructed_position": reconstructed_position if status == "metrics_available" else None,
        "pnl": pnl if status == "metrics_available" else None,
        "skipped_scans": skipped,
        "data_quality_warnings": warnings,
    }


async def reconstruct_scan_history(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> dict[str, Any]:
    """Return scan-history DCA reconstruction scoped to one authenticated user.

    The caller supplies the authenticated ``user_id`` and desired exchange. Only
    rows for that user are loaded; exchange is enforced via portfolio position
    context and, when present, the stored Analysis.parameters exchange value.
    """
    positions = await _load_positions(session, user_id, exchange, symbol)
    analyses = await _load_analyses(session, user_id, exchange, symbol, start_date, end_date)

    rows_by_symbol: dict[str, list[Analysis]] = {}
    for row in analyses:
        rows_by_symbol.setdefault(str(row.pair), []).append(row)

    symbols = sorted(set(rows_by_symbol) | set(positions))
    if symbol:
        symbols = [symbol] if symbol in set(symbols) | {symbol} else []

    coverages = [
        _coverage_for_symbol(sym, rows_by_symbol.get(sym, []), positions.get(sym))
        for sym in symbols
        if rows_by_symbol.get(sym) or positions.get(sym)
    ]

    return {
        "exchange": exchange,
        "method": METHOD_LABEL,
        "method_description": METHOD_DESCRIPTION,
        "fill_assumptions": _fill_assumptions(),
        "symbols": coverages,
    }
