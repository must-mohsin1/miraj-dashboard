"""Read-only desktop position-intelligence service.

This module owns the pure contract normalization for the Miraj Position menu-bar
surface.  It accepts already-authenticated, already-cached inputs from callers
and deliberately performs no route registration, exchange refresh, scan run,
order mutation, credential mutation, or database work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = 1
HTF_TIMEFRAMES: Tuple[Tuple[str, str], ...] = (("daily", "Daily"), ("weekly", "Weekly"))
LTF_TIMEFRAMES: Tuple[Tuple[str, str], ...] = (("1h", "1H"), ("4h", "4H"))
VALID_ADVISORY_ACTIONS = {"HOLD", "REDUCE", "CLOSE", "WAIT"}
ADVISORY_RANK = {"HOLD": 0, "WAIT": 1, "REDUCE": 2, "CLOSE": 3}
STRUCTURE_UNAVAILABLE_LABELS = {"", "UNKNOWN", "INSUFFICIENT DATA", "UNAVAILABLE"}


def build_desktop_position_intelligence(
    *,
    positions: Sequence[Dict[str, Any]],
    exchange: str = "mexc",
    selected_symbol: Optional[str] = None,
    scans_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    dca_recommendations_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    position_alerts_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    portfolio_last_refreshed: Optional[datetime] = None,
    mark_price_last_refreshed: Optional[datetime] = None,
    mark_price_source: str = "cached_position",
) -> Dict[str, Any]:
    """Build schema_version=1 desktop intelligence from cached/mock inputs only."""

    generated_at = _as_utc(now or datetime.now(timezone.utc))
    portfolio_refreshed = _as_utc(portfolio_last_refreshed or generated_at)
    mark_refreshed = _as_utc(mark_price_last_refreshed or portfolio_refreshed)
    pnl_age_seconds = max(0, int((generated_at - mark_refreshed).total_seconds()))

    errors: List[str] = []
    open_positions = [position for position in positions if _is_open_position(position)]
    selected_position, selection_reason = _select_position(open_positions, selected_symbol)

    scan: Optional[Dict[str, Any]] = None
    scan_missing = False
    position_payload: Optional[Dict[str, Any]] = None
    if selected_position is None:
        selection_reason = "no_open_positions"
    else:
        symbol = str(selected_position.get("symbol") or "")
        scan = _lookup_symbol(scans_by_symbol or {}, symbol)
        scan_missing = scan is None
        position_payload = _position_payload(
            position=selected_position,
            exchange=exchange,
            scan=scan,
            dca_recommendation=_lookup_symbol(dca_recommendations_by_symbol or {}, symbol),
            position_alerts=_lookup_symbol(position_alerts_by_symbol or {}, symbol),
            errors=errors,
        )

    stale_status = _stale_status(pnl_age_seconds, scan_missing=scan_missing)
    if stale_status == "critical_stale" and position_payload is not None:
        position_payload["advisory"]["reason"] = "Advisory: Open Miraj to refresh before acting"

    return {
        "schema_version": SCHEMA_VERSION,
        "exchange": exchange,
        "selection_reason": selection_reason,
        "generated_at": _isoformat_z(generated_at),
        "source": {
            "portfolio_last_refreshed": _isoformat_z(portfolio_refreshed),
            "mark_price_source": mark_price_source,
            "mark_price_last_refreshed": _isoformat_z(mark_refreshed),
            "pnl_age_seconds": pnl_age_seconds,
            "stale_status": stale_status,
            "refresh_executed": False,
        },
        "position": position_payload,
        "privacy": {"hide_amounts_available": True, "redaction_supported": True},
        "errors": errors,
    }


def _position_payload(
    *,
    position: Dict[str, Any],
    exchange: str,
    scan: Optional[Dict[str, Any]],
    dca_recommendation: Optional[Dict[str, Any]],
    position_alerts: Optional[Dict[str, Any]],
    errors: List[str],
) -> Dict[str, Any]:
    symbol = str(position.get("symbol") or "")
    side = _normal_side(position.get("side"))
    size_contracts = _float_value(
        position.get("size"),
        position.get("contracts"),
        position.get("size_contracts"),
        (position.get("info") or {}).get("holdVol") if isinstance(position.get("info"), dict) else None,
        default=0.0,
    )
    contract_size = _float_value(position.get("contract_size"), position.get("contractSize"), default=1.0)
    entry_price = _float_value(position.get("entry_price"), position.get("entryPrice"), default=0.0)
    mark_price = _float_value(position.get("mark_price"), position.get("markPrice"), default=entry_price)
    margin = _maybe_float(position.get("margin"), position.get("collateral"), position.get("initialMargin"))
    leverage = _float_value(position.get("leverage"), default=1.0)
    liquidation_price = _maybe_float(position.get("liquidation_price"), position.get("liquidationPrice"))

    pnl, pnl_formula = _pnl(position, side, entry_price, mark_price, size_contracts, contract_size)
    if margin is not None and margin > 0:
        pnl_percent = (pnl / margin) * 100.0
    else:
        pnl_percent = 0.0
        _add_error(errors, "margin_missing_for_pnl_percent")

    htf_sr = _sr_block(scan, mark_price, HTF_TIMEFRAMES)
    ltf_sr = _sr_block(scan, mark_price, LTF_TIMEFRAMES)
    advisory = _advisory(
        dca_recommendation=dca_recommendation,
        position_alerts=position_alerts,
        scan_available=_sr_available(htf_sr) or _sr_available(ltf_sr),
    )

    return {
        "symbol": symbol,
        "exchange": exchange,
        "side": side,
        "size_contracts": size_contracts,
        "contract_size": contract_size,
        "entry_price": entry_price,
        "mark_price": mark_price,
        "pnl": pnl,
        "pnl_percent": pnl_percent,
        "pnl_formula": pnl_formula,
        "margin": margin,
        "leverage": leverage,
        "liquidation_price": liquidation_price,
        "liquidation_distance_pct": _liquidation_distance_pct(mark_price, liquidation_price),
        "htf_sr": htf_sr,
        "ltf_sr": ltf_sr,
        "advisory": advisory,
        "dashboard_deeplink": f"/portfolio?exchange={exchange}&symbol={symbol}",
    }


def _select_position(
    open_positions: Sequence[Dict[str, Any]],
    selected_symbol: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], str]:
    if not open_positions:
        return None, "no_open_positions"

    if selected_symbol:
        selected_key = _symbol_key(selected_symbol)
        for position in open_positions:
            if _symbol_key(position.get("symbol")) == selected_key:
                return position, "user_selected"
        return _default_position(open_positions), "selected_position_closed_defaulted"

    return _default_position(open_positions), "no_user_selection_defaulted"


def _default_position(open_positions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return sorted(open_positions, key=lambda item: (-abs(_selection_pnl(item)), _symbol_key(item.get("symbol"))))[0]


def _selection_pnl(position: Dict[str, Any]) -> float:
    exchange_pnl = _maybe_float(position.get("unrealizedPnl"), position.get("pnl"), position.get("unRealizedPnl"))
    if exchange_pnl is not None:
        return exchange_pnl
    side = _normal_side(position.get("side"))
    return _computed_pnl(
        side,
        _float_value(position.get("entry_price"), position.get("entryPrice"), default=0.0),
        _float_value(position.get("mark_price"), position.get("markPrice"), default=0.0),
        _float_value(position.get("size"), position.get("contracts"), default=0.0),
        _float_value(position.get("contract_size"), position.get("contractSize"), default=1.0),
    )


def _pnl(
    position: Dict[str, Any],
    side: str,
    entry_price: float,
    mark_price: float,
    size_contracts: float,
    contract_size: float,
) -> Tuple[float, str]:
    supplied = _maybe_float(position.get("unrealizedPnl"), position.get("unRealizedPnl"), position.get("pnl"))
    if supplied is not None:
        return supplied, "exchange_unrealized_pnl"
    return _computed_pnl(side, entry_price, mark_price, size_contracts, contract_size), "computed_contracts_contract_size"


def _computed_pnl(side: str, entry_price: float, mark_price: float, size_contracts: float, contract_size: float) -> float:
    if side == "SHORT":
        return (entry_price - mark_price) * size_contracts * contract_size
    return (mark_price - entry_price) * size_contracts * contract_size


def _sr_block(
    scan: Optional[Dict[str, Any]],
    mark_price: float,
    timeframes: Tuple[Tuple[str, str], ...],
) -> Dict[str, Any]:
    labels = [label for _, label in timeframes]
    if not isinstance(scan, dict):
        return _unavailable_sr(labels)

    support_candidates: List[Dict[str, Any]] = []
    resistance_candidates: List[Dict[str, Any]] = []
    structure_label = "unknown"
    structure_seen = False
    structure = scan.get("structure") or {}

    for key, label in timeframes:
        tf_structure = structure.get(key)
        if not isinstance(tf_structure, dict):
            continue
        label_value = str(tf_structure.get("label") or "unknown").upper()
        if label_value not in STRUCTURE_UNAVAILABLE_LABELS and structure_label == "unknown":
            structure_label = label_value
            structure_seen = True
        for swing in _swing_iter(tf_structure.get("swings")):
            price = _maybe_float(swing.get("price"))
            if price is None:
                continue
            swing_type = str(swing.get("type") or swing.get("swing_type") or "").lower()
            level = {
                "price": price,
                "distance_pct": _level_distance_pct(mark_price, price),
                "method": "smc_swing",
                "timeframe": label,
                "swing_type": _contract_swing_type(swing_type),
                "swing_index": swing.get("index", swing.get("swing_index")),
            }
            if swing_type == "low" and price <= mark_price:
                support_candidates.append(level)
            elif swing_type == "high" and price >= mark_price:
                resistance_candidates.append(level)

    support = max(support_candidates, key=lambda item: item["price"], default=None)
    resistance = min(resistance_candidates, key=lambda item: item["price"], default=None)
    if not structure_seen and support is None and resistance is None:
        return _unavailable_sr(labels)

    confidence = "HIGH" if structure_seen and (support is not None or resistance is not None) else "LOW"
    return {
        "timeframes": labels,
        "support": support,
        "resistance": resistance,
        "structure_label": structure_label,
        "confidence": confidence,
    }


def _unavailable_sr(labels: List[str]) -> Dict[str, Any]:
    return {
        "timeframes": labels,
        "support": None,
        "resistance": None,
        "structure_label": "Insufficient data",
        "confidence": "UNAVAILABLE",
    }


def _sr_available(sr_block: Dict[str, Any]) -> bool:
    return sr_block.get("confidence") != "UNAVAILABLE"


def _advisory(
    *,
    dca_recommendation: Optional[Dict[str, Any]],
    position_alerts: Optional[Dict[str, Any]],
    scan_available: bool,
) -> Dict[str, Any]:
    candidates: List[Tuple[str, str, str, str]] = []

    dca_action = str((dca_recommendation or {}).get("recommendation") or "HOLD").upper()
    if dca_action == "CLOSE":
        candidates.append(("CLOSE", "DANGER", "DCA recommends closing risk; open Miraj to review.", "dca"))
    elif dca_action == "REDUCE":
        candidates.append(("REDUCE", "WARNING", "DCA recommends reducing exposure; open Miraj to review.", "dca"))
    elif dca_action == "ADD":
        candidates.append(("WAIT", "INFO", "Open Miraj before changing the position; desktop ADD maps to WAIT.", "dca"))
    elif dca_action == "HOLD":
        candidates.append(("HOLD", "INFO", "Position context supports holding for now.", "dca"))
    else:
        candidates.append(("WAIT", "INFO", "Open Miraj to review this unsupported recommendation.", "dca"))

    max_severity = str((position_alerts or {}).get("max_severity") or "").upper()
    alerts = (position_alerts or {}).get("alerts") or []
    if max_severity == "DANGER" or any(str(a.get("severity") or "").upper() == "DANGER" for a in alerts if isinstance(a, dict)):
        candidates.append(("CLOSE", "DANGER", "Danger alert is active; open Miraj to review.", "position_alert"))
    elif max_severity == "WARNING" or any(str(a.get("severity") or "").upper() == "WARNING" for a in alerts if isinstance(a, dict)):
        candidates.append(("REDUCE", "WARNING", "Warning alert is active; open Miraj to review.", "position_alert"))

    if not scan_available:
        candidates.append(("WAIT", "INFO", "Scan context is unavailable; open Miraj before acting.", "fallback"))

    action, severity, reason, source = max(candidates, key=lambda candidate: ADVISORY_RANK[candidate[0]])
    if len({candidate[3] for candidate in candidates}) > 1:
        source = "combined"
    return {
        "action": action if action in VALID_ADVISORY_ACTIONS else "WAIT",
        "severity": severity,
        "reason": _advisory_reason(reason),
        "source": source,
        "action_items_count": len(alerts) if isinstance(alerts, list) else 0,
    }


def _advisory_reason(reason: str) -> str:
    safe = reason.replace("Add now", "Open Miraj").replace("Close now", "Open Miraj").replace("Reduce now", "Open Miraj")
    if len(safe) > 110:
        safe = safe[:107].rstrip() + "..."
    return f"Advisory: {safe}"


def _stale_status(pnl_age_seconds: int, *, scan_missing: bool) -> str:
    if pnl_age_seconds > 900:
        return "critical_stale"
    if pnl_age_seconds > 120 or scan_missing:
        return "stale"
    return "fresh"


def _lookup_symbol(mapping: Dict[str, Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
    wanted = _symbol_key(symbol)
    for key, value in mapping.items():
        if _symbol_key(key) == wanted:
            return value
    return None


def _is_open_position(position: Dict[str, Any]) -> bool:
    return abs(_float_value(position.get("size"), position.get("contracts"), position.get("size_contracts"), default=0.0)) > 0


def _normal_side(value: Any) -> str:
    side = str(value or "LONG").upper()
    if side in {"SHORT", "SELL"}:
        return "SHORT"
    return "LONG"


def _symbol_key(value: Any) -> str:
    return str(value or "").upper().replace("/", "").replace(":USDT", "").replace("-", "")


def _float_value(*values: Any, default: float) -> float:
    maybe = _maybe_float(*values)
    return default if maybe is None else maybe


def _maybe_float(*values: Any) -> Optional[float]:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _swing_iter(swings: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(swings, list):
        return []
    return [swing for swing in swings if isinstance(swing, dict)]


def _liquidation_distance_pct(mark_price: float, liquidation_price: Optional[float]) -> Optional[float]:
    if liquidation_price is None or liquidation_price <= 0 or mark_price <= 0:
        return None
    return abs(mark_price - liquidation_price) / mark_price * 100.0


def _level_distance_pct(mark_price: float, level_price: float) -> Optional[float]:
    if mark_price <= 0:
        return None
    return (level_price - mark_price) / mark_price * 100.0


def _contract_swing_type(swing_type: str) -> str:
    if swing_type in {"low", "swing_low"}:
        return "swing_low"
    if swing_type in {"high", "swing_high"}:
        return "swing_high"
    return swing_type


def _add_error(errors: List[str], code: str) -> None:
    if code not in errors:
        errors.append(code)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
