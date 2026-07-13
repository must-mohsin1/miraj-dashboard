"""DCA shadow-mode safety-gate evaluator.

This service is deliberately non-live: it evaluates current DCA recommendations,
persists an audit row, and never creates, signs, queues, submits, or simulates an
exchange order object.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

try:  # Models are supplied by the persistence slice; tests monkeypatch these.
    from backend.models import (  # type: ignore[attr-defined]
        DcaShadowDecisionHistory,
        DcaShadowGlobalKillSwitch,
        DcaShadowSymbolKillSwitch,
        DcaShadowUserKillSwitch,
    )
except ImportError:  # pragma: no cover - exercised only before persistence is integrated.
    DcaShadowDecisionHistory = None  # type: ignore[assignment]
    DcaShadowGlobalKillSwitch = None  # type: ignore[assignment]
    DcaShadowSymbolKillSwitch = None  # type: ignore[assignment]
    DcaShadowUserKillSwitch = None  # type: ignore[assignment]

ADD_HOURLY_LIMIT = 3
ADD_DAILY_LIMIT = 10
CLOSE_COOLDOWN_HOURS = 24
MAX_ADD_SIZE_PCT_PORTFOLIO = 0.10
DEFAULT_EXPOSURE_CAP_PCT = 0.25
MIN_CONFLUENCE_SCORE = 10.0

DEFAULT_ASSUMPTION_SET: Dict[str, Any] = {
    "mode": "shadow_non_live",
    "live_execution": False,
    "outcomes": ["would_allow", "would_block", "would_reduce", "would_close", "no_action"],
    "min_confluence_score": MIN_CONFLUENCE_SCORE,
    "hourly_add_limit": ADD_HOURLY_LIMIT,
    "daily_add_limit": ADD_DAILY_LIMIT,
    "close_cooldown_hours": CLOSE_COOLDOWN_HOURS,
    "max_add_size_pct_portfolio": MAX_ADD_SIZE_PCT_PORTFOLIO,
    "default_exposure_cap_pct": DEFAULT_EXPOSURE_CAP_PCT,
}


async def evaluate_shadow_decision(
    *,
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: str,
    recommendation: Dict[str, Any],
    scan: Optional[Dict[str, Any]] = None,
    portfolio_value: float,
    current_dca_exposure: float,
    simulated_add_size: Optional[float] = None,
    exposure_cap_pct: float = DEFAULT_EXPOSURE_CAP_PCT,
    now: Optional[datetime] = None,
    assumption_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate and audit one shadow-mode DCA decision.

    The evaluator only returns non-live outcomes:
    ``would_allow``, ``would_block``, ``would_reduce``, ``would_close``, or
    ``no_action``. It never imports exchange placement helpers or creates any
    order-like exchange payload.
    """

    _require_shadow_models()
    timestamp = _to_naive_utc(now or datetime.now(timezone.utc))
    original = str(recommendation.get("recommendation") or "HOLD").upper()
    assumption_set = {
        **DEFAULT_ASSUMPTION_SET,
        "exposure_cap_pct": exposure_cap_pct,
        "portfolio_value": float(portfolio_value or 0.0),
        "current_dca_exposure": float(current_dca_exposure or 0.0),
    }
    if assumption_overrides:
        assumption_set.update(assumption_overrides)

    if original == "ADD":
        add_size = _extract_add_size(recommendation, simulated_add_size)
        assumption_set["simulated_add_size"] = add_size
        gate_breakdown = await _evaluate_add_gates(
            session=session,
            user_id=user_id,
            exchange=exchange,
            symbol=symbol,
            recommendation=recommendation,
            scan=scan or {},
            portfolio_value=float(portfolio_value or 0.0),
            current_dca_exposure=float(current_dca_exposure or 0.0),
            simulated_add_size=add_size,
            exposure_cap_pct=exposure_cap_pct,
            now=timestamp,
        )
        blocked_gates = [gate["name"] for gate in gate_breakdown if not gate["passed"]]
        final_outcome = "would_block" if blocked_gates else "would_allow"
        final_reason = _add_final_reason(final_outcome, gate_breakdown)
    elif original == "CLOSE":
        gate_breakdown = [
            _gate(
                "urgent_risk_preserved",
                True,
                "REDUCE/CLOSE recommendations bypass ADD-only kill switches and safety gates.",
            ),
            _gate("non_live_outcome", True, "Shadow mode records would_close only; no live order is placed."),
        ]
        blocked_gates = []
        final_outcome = "would_close"
        final_reason = _risk_final_reason("would_close", recommendation)
    elif original == "REDUCE":
        gate_breakdown = [
            _gate(
                "urgent_risk_preserved",
                True,
                "REDUCE/CLOSE recommendations bypass ADD-only kill switches and safety gates.",
            ),
            _gate("non_live_outcome", True, "Shadow mode records would_reduce only; no live order is placed."),
        ]
        blocked_gates = []
        final_outcome = "would_reduce"
        final_reason = _risk_final_reason("would_reduce", recommendation)
    else:
        gate_breakdown = [
            _gate("no_add_recommendation", True, f"Original recommendation is {original}; no ADD action is proposed."),
            _gate("non_live_outcome", True, "Shadow mode records no_action only; no live order is placed."),
        ]
        blocked_gates = []
        final_outcome = "no_action"
        reason = recommendation.get("reason") or "No ADD, REDUCE, or CLOSE recommendation is present."
        final_reason = f"No shadow action: {reason}"

    decision = {
        "timestamp": timestamp.isoformat() + "Z",
        "exchange": exchange,
        "symbol": symbol,
        "original_recommendation": original,
        "final_outcome": final_outcome,
        "gate_breakdown": gate_breakdown,
        "blocked_gates": blocked_gates,
        "assumption_set": assumption_set,
        "final_reason": final_reason,
    }
    await _persist_decision(
        session=session,
        user_id=user_id,
        exchange=exchange,
        symbol=symbol,
        timestamp=timestamp,
        original_recommendation=original,
        final_outcome=final_outcome,
        gate_breakdown=gate_breakdown,
        blocked_gates=blocked_gates,
        assumption_set=assumption_set,
        final_reason=final_reason,
    )
    return decision


async def list_shadow_history(
    *,
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: Optional[str] = None,
    outcome: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return audited shadow history filtered to one authenticated user."""

    _require_shadow_models()
    stmt = select(DcaShadowDecisionHistory).where(  # type: ignore[arg-type,union-attr]
        DcaShadowDecisionHistory.user_id == user_id,
        DcaShadowDecisionHistory.exchange == exchange,
    )
    if symbol:
        stmt = stmt.where(DcaShadowDecisionHistory.symbol == symbol)
    if outcome:
        stmt = stmt.where(DcaShadowDecisionHistory.final_outcome == outcome)
    if start:
        stmt = stmt.where(DcaShadowDecisionHistory.timestamp >= _to_naive_utc(start))
    if end:
        stmt = stmt.where(DcaShadowDecisionHistory.timestamp <= _to_naive_utc(end))
    stmt = stmt.order_by(DcaShadowDecisionHistory.timestamp.desc()).limit(max(1, min(limit, 200)))
    rows = list((await session.execute(stmt)).scalars().all())
    return [_history_row(row) for row in rows]


async def _evaluate_add_gates(
    *,
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: str,
    recommendation: Dict[str, Any],
    scan: Dict[str, Any],
    portfolio_value: float,
    current_dca_exposure: float,
    simulated_add_size: float,
    exposure_cap_pct: float,
    now: datetime,
) -> List[Dict[str, Any]]:
    confluence = _extract_confluence_score(recommendation, scan)
    dca_safe, dca_reason = _extract_dca_safe(scan, recommendation)
    global_switch = await _active_global_kill_switch(session)
    user_switch = await _active_user_kill_switch(session, user_id)
    symbol_switch = await _active_symbol_kill_switch(session, user_id, exchange, symbol)
    hourly_adds = await _allowed_add_count(session, user_id, now - timedelta(hours=1), now)
    daily_adds = await _allowed_add_count(session, user_id, datetime.combine(now.date(), time.min), now)
    recent_close = await _recent_close_for_symbol(session, user_id, exchange, symbol, now)

    add_size_limit = portfolio_value * MAX_ADD_SIZE_PCT_PORTFOLIO if portfolio_value > 0 else 0.0
    exposure_cap_value = portfolio_value * exposure_cap_pct if portfolio_value > 0 else 0.0
    projected_exposure = current_dca_exposure + simulated_add_size

    return [
        _gate("dca_safe", dca_safe, dca_reason),
        _gate(
            "confluence_score",
            confluence >= MIN_CONFLUENCE_SCORE,
            f"Confluence score {confluence:.1f} must be at least {MIN_CONFLUENCE_SCORE:.0f}.",
            {"score": confluence, "minimum": MIN_CONFLUENCE_SCORE},
        ),
        _gate(
            "global_kill_switch",
            global_switch is None,
            _kill_switch_reason("Global/admin ADD kill switch", global_switch),
        ),
        _gate(
            "user_kill_switch",
            user_switch is None,
            _kill_switch_reason("User ADD kill switch", user_switch),
        ),
        _gate(
            "symbol_kill_switch",
            symbol_switch is None,
            _kill_switch_reason("Symbol ADD kill switch", symbol_switch),
        ),
        _gate(
            "hourly_add_limit",
            hourly_adds < ADD_HOURLY_LIMIT,
            f"User has {hourly_adds} allowed ADD decisions in the last hour; limit is {ADD_HOURLY_LIMIT}.",
            {"count": hourly_adds, "limit": ADD_HOURLY_LIMIT},
        ),
        _gate(
            "daily_add_limit",
            daily_adds < ADD_DAILY_LIMIT,
            f"User has {daily_adds} allowed ADD decisions today; limit is {ADD_DAILY_LIMIT}.",
            {"count": daily_adds, "limit": ADD_DAILY_LIMIT},
        ),
        _gate(
            "close_cooldown_24h",
            recent_close is None,
            "Symbol is inside the 24-hour cooldown after a CLOSE." if recent_close else "No CLOSE cooldown is active for this symbol.",
        ),
        _gate(
            "add_size_pct_portfolio",
            portfolio_value > 0 and simulated_add_size <= add_size_limit,
            f"Simulated ADD size ${simulated_add_size:.2f} must be <= 10% of portfolio (${add_size_limit:.2f}).",
            {"simulated_add_size": simulated_add_size, "limit_value": add_size_limit},
        ),
        _gate(
            "exposure_cap",
            portfolio_value > 0 and projected_exposure <= exposure_cap_value,
            f"Projected DCA exposure ${projected_exposure:.2f} must be <= exposure cap ${exposure_cap_value:.2f}.",
            {"projected_exposure": projected_exposure, "cap_value": exposure_cap_value, "cap_pct": exposure_cap_pct},
        ),
    ]


def _gate(name: str, passed: bool, reason: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    gate = {"name": name, "passed": bool(passed), "reason": reason}
    if details is not None:
        gate["details"] = details
    return gate


def _add_final_reason(final_outcome: str, gate_breakdown: List[Dict[str, Any]]) -> str:
    if final_outcome == "would_allow":
        return "Shadow ADD would be allowed: all visible safety gates passed. No live order was placed."
    failed = [gate for gate in gate_breakdown if not gate["passed"]]
    labels = [_human_gate_name(gate["name"]) for gate in failed]
    return "Shadow ADD would be blocked because these gates failed: " + ", ".join(labels) + ". No live order was placed."


def _risk_final_reason(outcome: str, recommendation: Dict[str, Any]) -> str:
    original_reason = recommendation.get("reason") or "risk-management recommendation"
    action = "CLOSE" if outcome == "would_close" else "REDUCE"
    return f"Shadow {action} would be shown because: {original_reason} No live order was placed."


def _human_gate_name(name: str) -> str:
    return {
        "dca_safe": "DCA SAFE checklist",
        "confluence_score": "confluence score",
        "global_kill_switch": "global kill switch",
        "user_kill_switch": "user kill switch",
        "symbol_kill_switch": "symbol kill switch",
        "hourly_add_limit": "hourly ADD limit",
        "daily_add_limit": "daily ADD limit",
        "close_cooldown_24h": "24-hour CLOSE cooldown",
        "add_size_pct_portfolio": "simulated ADD size",
        "exposure_cap": "DCA exposure cap",
    }.get(name, name.replace("_", " "))


def _extract_add_size(recommendation: Dict[str, Any], explicit_size: Optional[float]) -> float:
    if explicit_size is not None:
        return max(0.0, float(explicit_size))
    for key in ("simulated_add_size", "add_size", "notional", "size_usd"):
        value = recommendation.get(key)
        if isinstance(value, (int, float)):
            return max(0.0, float(value))
    return 0.0


def _extract_confluence_score(recommendation: Dict[str, Any], scan: Dict[str, Any]) -> float:
    for source in (recommendation, scan):
        value = source.get("confluence_score") or source.get("score")
        if isinstance(value, (int, float)):
            return float(value)
    breakdown = scan.get("score_breakdown")
    if isinstance(breakdown, dict):
        value = breakdown.get("total")
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _extract_dca_safe(scan: Dict[str, Any], recommendation: Dict[str, Any]) -> tuple[bool, str]:
    if isinstance(recommendation.get("dca_safe"), bool):
        safe = bool(recommendation["dca_safe"])
        return safe, "DCA SAFE checklist passed." if safe else "DCA SAFE checklist did not pass."
    validation = scan.get("dca_validation")
    if isinstance(validation, dict):
        if isinstance(validation.get("dca_safe"), bool):
            safe = bool(validation["dca_safe"])
            return safe, "DCA SAFE checklist passed." if safe else "DCA SAFE checklist did not pass."
        checks = validation.get("checks")
        if isinstance(checks, dict) and checks:
            failed = [str(name) for name, passed in checks.items() if not bool(passed)]
            if failed:
                return False, "DCA SAFE checklist failed: " + ", ".join(failed) + "."
            return True, "DCA SAFE checklist passed."
    if isinstance(scan.get("dca_safe"), bool):
        safe = bool(scan["dca_safe"])
        return safe, "DCA SAFE checklist passed." if safe else "DCA SAFE checklist did not pass."
    return False, "DCA SAFE checklist is unavailable, so the ADD cannot be allowed."


async def _active_global_kill_switch(session: AsyncSession) -> Optional[Any]:
    stmt = select(DcaShadowGlobalKillSwitch).where(DcaShadowGlobalKillSwitch.active.is_(True))  # type: ignore[union-attr]
    return (await session.execute(stmt)).scalars().first()


async def _active_user_kill_switch(session: AsyncSession, user_id: int) -> Optional[Any]:
    stmt = select(DcaShadowUserKillSwitch).where(  # type: ignore[union-attr]
        DcaShadowUserKillSwitch.user_id == user_id,
        DcaShadowUserKillSwitch.active.is_(True),
    )
    return (await session.execute(stmt)).scalars().first()


async def _active_symbol_kill_switch(session: AsyncSession, user_id: int, exchange: str, symbol: str) -> Optional[Any]:
    stmt = select(DcaShadowSymbolKillSwitch).where(  # type: ignore[union-attr]
        DcaShadowSymbolKillSwitch.user_id == user_id,
        DcaShadowSymbolKillSwitch.exchange == exchange,
        DcaShadowSymbolKillSwitch.symbol == symbol,
        DcaShadowSymbolKillSwitch.active.is_(True),
    )
    return (await session.execute(stmt)).scalars().first()


async def _allowed_add_count(session: AsyncSession, user_id: int, start: datetime, end: datetime) -> int:
    stmt = select(func.count()).select_from(DcaShadowDecisionHistory).where(  # type: ignore[arg-type]
        DcaShadowDecisionHistory.user_id == user_id,
        DcaShadowDecisionHistory.original_recommendation == "ADD",
        DcaShadowDecisionHistory.final_outcome == "would_allow",
        DcaShadowDecisionHistory.timestamp >= start,
        DcaShadowDecisionHistory.timestamp <= end,
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


async def _recent_close_for_symbol(
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: str,
    now: datetime,
) -> Optional[Any]:
    stmt = select(DcaShadowDecisionHistory).where(  # type: ignore[union-attr]
        DcaShadowDecisionHistory.user_id == user_id,
        DcaShadowDecisionHistory.exchange == exchange,
        DcaShadowDecisionHistory.symbol == symbol,
        DcaShadowDecisionHistory.final_outcome == "would_close",
        DcaShadowDecisionHistory.timestamp >= now - timedelta(hours=CLOSE_COOLDOWN_HOURS),
    )
    return (await session.execute(stmt)).scalars().first()


def _kill_switch_reason(label: str, switch: Optional[Any]) -> str:
    if switch is None:
        return f"{label} is not active."
    reason = getattr(switch, "reason", None)
    suffix = f": {reason}" if reason else "."
    return f"{label} is active{suffix}"


async def _persist_decision(
    *,
    session: AsyncSession,
    user_id: int,
    exchange: str,
    symbol: str,
    timestamp: datetime,
    original_recommendation: str,
    final_outcome: str,
    gate_breakdown: List[Dict[str, Any]],
    blocked_gates: List[str],
    assumption_set: Dict[str, Any],
    final_reason: str,
) -> None:
    row = DcaShadowDecisionHistory(  # type: ignore[operator]
        user_id=user_id,
        timestamp=timestamp,
        exchange=exchange,
        symbol=symbol,
        original_recommendation=original_recommendation,
        final_outcome=final_outcome,
        gate_breakdown=gate_breakdown,
        blocked_gates=blocked_gates,
        assumption_set=assumption_set,
        final_reason=final_reason,
    )
    session.add(row)
    await session.flush()


def _history_row(row: Any) -> Dict[str, Any]:
    ts = getattr(row, "timestamp", None)
    return {
        "timestamp": ts.isoformat() + "Z" if isinstance(ts, datetime) else None,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "original_recommendation": row.original_recommendation,
        "final_outcome": row.final_outcome,
        "gate_breakdown": row.gate_breakdown,
        "blocked_gates": row.blocked_gates,
        "assumption_set": row.assumption_set,
        "final_reason": row.final_reason,
    }


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _require_shadow_models() -> None:
    missing = [
        name
        for name, value in {
            "DcaShadowDecisionHistory": DcaShadowDecisionHistory,
            "DcaShadowGlobalKillSwitch": DcaShadowGlobalKillSwitch,
            "DcaShadowUserKillSwitch": DcaShadowUserKillSwitch,
            "DcaShadowSymbolKillSwitch": DcaShadowSymbolKillSwitch,
        }.items()
        if value is None
    ]
    if missing:
        raise RuntimeError(
            "DCA shadow persistence models are unavailable: " + ", ".join(missing)
        )
