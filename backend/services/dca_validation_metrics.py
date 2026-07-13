"""DCA validation metrics computed from scan-history reconstruction output.

The functions in this module are intentionally pure: callers pass the
reconstruction payload produced by the scan-history reconstruction service and
receive per-symbol, portfolio, DCA-specific, and walk-forward metrics without
querying routes, models, or external price sources.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any

MIN_RETURN_OBSERVATIONS = 2
MIN_RECOMMENDATION_EVENTS_FOR_BIAS_CHECK = 30
SCAN_GAP_WARNING_SECONDS = 48 * 60 * 60
ENTRY_ALLOCATIONS = {1: 20.0, 2: 20.0, 3: 60.0}


def compute_dca_validation_metrics(
    reconstruction: dict[str, Any],
    *,
    split_ratio: float = 0.7,
) -> dict[str, Any]:
    """Compute validation metrics from reconstruction output.

    ``reconstruction`` is expected to contain a ``symbols`` list whose entries
    match the scan-history coverage shape: events, reconstructed_position, pnl,
    scan coverage, and data-quality warnings. Multiple entries with the same
    symbol are folded together chronologically so tests and future callers can
    represent more than one reconstructed trade for a symbol.
    """
    if not 0 < split_ratio < 1:
        raise ValueError("split_ratio must be greater than 0 and less than 1")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for coverage in reconstruction.get("symbols") or []:
        symbol = str(coverage.get("symbol") or "")
        if symbol:
            grouped[symbol].append(coverage)

    symbols = [
        _symbol_metrics(symbol, coverages, split_ratio)
        for symbol, coverages in sorted(grouped.items())
    ]
    all_trades = [trade for item in symbols for trade in item["_trades"]]
    for item in symbols:
        item.pop("_trades", None)

    return {
        "exchange": reconstruction.get("exchange"),
        "split_ratio": split_ratio,
        "symbols": symbols,
        "portfolio": {
            "metrics": _trade_metrics(all_trades),
            "dca_metrics": _portfolio_dca_metrics(symbols),
            "buy_and_hold_benchmark": _benchmark_unavailable(),
        },
    }


def _symbol_metrics(symbol: str, coverages: list[dict[str, Any]], split_ratio: float) -> dict[str, Any]:
    ordered = sorted(coverages, key=lambda item: item.get("first_scan_at") or "")
    events = [event for coverage in ordered for event in (coverage.get("events") or [])]
    trades = [_trade_from_coverage(coverage) for coverage in ordered]
    trades = [trade for trade in trades if trade is not None]
    insufficient_reasons = _insufficient_reasons(ordered, trades)

    warnings = _warnings(ordered, events, trades, split_ratio)
    benchmark = _benchmark_unavailable()
    if benchmark["reason"] and "missing_benchmark_data" not in warnings:
        warnings.append("missing_benchmark_data")

    return {
        "symbol": symbol,
        "status": "metrics_available" if trades else "insufficient_history",
        "scan_count": sum(int(coverage.get("scan_count") or 0) for coverage in ordered),
        "first_scan_at": _min_text(coverage.get("first_scan_at") for coverage in ordered),
        "last_scan_at": _max_text(coverage.get("last_scan_at") for coverage in ordered),
        "insufficient_reasons": insufficient_reasons,
        "metrics": _trade_metrics(trades),
        "dca_metrics": _dca_metrics(events, trades),
        "walk_forward": _walk_forward(trades, split_ratio),
        "buy_and_hold_benchmark": benchmark,
        "warnings": warnings,
        "_trades": trades,
    }


def _trade_from_coverage(coverage: dict[str, Any]) -> dict[str, Any] | None:
    pnl = coverage.get("pnl")
    position = coverage.get("reconstructed_position")
    if not isinstance(pnl, dict) or not isinstance(position, dict):
        return None

    fills = position.get("fills") or []
    if not fills:
        return None

    scan_start = _parse_dt(coverage.get("first_scan_at"))
    start = _parse_dt(fills[0].get("timestamp")) or scan_start
    end = _parse_dt(position.get("exit_timestamp") or position.get("valuation_timestamp") or coverage.get("last_scan_at"))
    net_pnl = _float(pnl.get("net_pnl")) or 0.0
    notional = sum(_float(fill.get("notional")) or 0.0 for fill in fills)
    if notional <= 0:
        notional = sum(abs((_float(fill.get("fill_price")) or 0.0) * (_float(fill.get("quantity")) or 0.0)) for fill in fills)

    return {
        "symbol": coverage.get("symbol"),
        "net_pnl": net_pnl,
        "return_pct": (net_pnl / notional) * 100 if notional else None,
        "notional": notional,
        "start": start,
        "scan_start": scan_start or start,
        "end": end,
        "fills": fills,
        "events": coverage.get("events") or [],
        "max_scan_gap_seconds": coverage.get("max_scan_gap_seconds"),
    }


def _trade_metrics(trades: list[dict[str, Any]], insufficient_reason: str | None = None) -> dict[str, dict[str, Any]]:
    if not trades:
        reason = insufficient_reason or "fewer_than_1_reconstructed_trades"
        return {
            "win_rate": _metric(None, reason),
            "total_return": _metric(None, reason),
            "gross_profit": _metric(None, reason),
            "gross_loss": _metric(None, reason),
            "profit_factor": _metric(None, reason),
            "max_drawdown_absolute": _metric(None, reason),
            "max_drawdown_percent": _metric(None, reason),
            "sharpe": _metric(None, "fewer_than_2_return_observations"),
            "sortino": _metric(None, "fewer_than_2_return_observations"),
            "average_hold_time_hours": _metric(None, reason),
            "exposure_percentage": _metric(None, reason),
            "reconstructed_trade_count": _metric(0),
        }

    pnls = [float(trade["net_pnl"]) for trade in trades]
    returns = [trade["return_pct"] for trade in trades if trade.get("return_pct") is not None]
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    total_notional = sum(float(trade.get("notional") or 0.0) for trade in trades)
    total_pnl = sum(pnls)
    max_dd, max_dd_pct = _max_drawdown(pnls)

    return {
        "win_rate": _metric(round((sum(1 for value in pnls if value > 0) / len(pnls)) * 100, 2)),
        "total_return": _metric(round((total_pnl / total_notional) * 100, 4) if total_notional else None, None if total_notional else "missing_notional"),
        "gross_profit": _metric(round(gross_profit, 2)),
        "gross_loss": _metric(round(gross_loss, 2)),
        "profit_factor": _profit_factor(gross_profit, gross_loss),
        "max_drawdown_absolute": _metric(round(max_dd, 2)),
        "max_drawdown_percent": _metric(round(max_dd_pct, 2) if max_dd_pct is not None else 0.0),
        "sharpe": _sharpe(returns),
        "sortino": _sortino(returns),
        "average_hold_time_hours": _metric(_average_hold_hours(trades)),
        "exposure_percentage": _metric(round(_average_exposure(trades), 2)),
        "reconstructed_trade_count": _metric(len(trades)),
    }


def _dca_metrics(events: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    add_events = [event for event in events if event.get("recommendation") == "ADD"]
    fills = [fill for trade in trades for fill in trade.get("fills", [])]
    levels = {int(fill.get("level")) for fill in fills if _float(fill.get("level")) is not None}
    follow_through = [event for event in add_events if event.get("fill_price") is not None or event.get("entry_level") is not None]
    safe_labels = [event for event in add_events if isinstance(event.get("dca_safe"), bool)]

    return {
        "entry_level_completion_rate": _metric(round(len(levels & {1, 2, 3}) / 3, 4) if trades else None, None if trades else "fewer_than_1_reconstructed_trades"),
        "average_entry_price_vs_planned_zone": _planned_zone_metric(add_events, fills),
        "add_follow_through_rate": _metric(round(len(follow_through) / len(add_events), 4) if add_events else None, None if add_events else "no_add_recommendations"),
        "dca_safe_flag_accuracy": _safe_accuracy(safe_labels, trades),
        "three_entry_completion_rate": _metric(round(sum(1 for trade in trades if len({fill.get("level") for fill in trade.get("fills", [])}) >= 3) / len(trades), 4) if trades else None, None if trades else "fewer_than_1_reconstructed_trades"),
    }


def _portfolio_dca_metrics(symbols: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    keys = [
        "entry_level_completion_rate",
        "add_follow_through_rate",
        "dca_safe_flag_accuracy",
        "three_entry_completion_rate",
    ]
    result: dict[str, dict[str, Any]] = {}
    for key in keys:
        values = [item["dca_metrics"][key]["value"] for item in symbols if item["dca_metrics"][key]["value"] is not None]
        result[key] = _metric(round(statistics.mean(values), 4) if values else None, None if values else "no_symbol_values")
    return result


def _walk_forward(trades: list[dict[str, Any]], split_ratio: float) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda trade: trade.get("end") or datetime.min)
    if not ordered:
        return {
            "split_ratio": split_ratio,
            "in_sample": {"date_range": {"start": None, "end": None}, "metrics": _trade_metrics([])},
            "out_of_sample": {"date_range": {"start": None, "end": None}, "metrics": _trade_metrics([])},
        }

    split_at = max(1, min(len(ordered), math.ceil(len(ordered) * split_ratio)))
    if split_at == len(ordered) and len(ordered) > 1:
        split_at = len(ordered) - 1
    in_sample = ordered[:split_at]
    out_sample = ordered[split_at:]
    return {
        "split_ratio": split_ratio,
        "in_sample": {"date_range": _date_range(in_sample), "metrics": _trade_metrics(in_sample)},
        "out_of_sample": {"date_range": _date_range(out_sample), "metrics": _trade_metrics(out_sample)},
    }


def _warnings(coverages: list[dict[str, Any]], events: list[dict[str, Any]], trades: list[dict[str, Any]], split_ratio: float) -> list[str]:
    warnings: list[str] = []
    if any((_float(coverage.get("max_scan_gap_seconds")) or 0) > SCAN_GAP_WARNING_SECONDS for coverage in coverages):
        warnings.append("scan_gap_over_48_hours")
    if len([event for event in events if event.get("participates_in_metrics")]) < MIN_RECOMMENDATION_EVENTS_FOR_BIAS_CHECK:
        warnings.append("fewer_than_30_reconstructed_recommendation_events")
    if trades:
        wf = _walk_forward(trades, split_ratio)
        in_return = wf["in_sample"]["metrics"]["total_return"]["value"]
        out_return = wf["out_of_sample"]["metrics"]["total_return"]["value"]
        if in_return is not None and out_return is not None and out_return < in_return:
            warnings.append("out_of_sample_underperformed_in_sample")
    for coverage in coverages:
        for warning in coverage.get("data_quality_warnings") or []:
            if warning not in warnings:
                warnings.append(warning)
    return warnings


def _profit_factor(gross_profit: float, gross_loss: float) -> dict[str, Any]:
    if gross_loss == 0:
        return _metric(None, "gross_loss_is_zero")
    return _metric(round(gross_profit / gross_loss, 4))


def _sharpe(returns: list[float]) -> dict[str, Any]:
    if len(returns) < MIN_RETURN_OBSERVATIONS:
        return _metric(None, "fewer_than_2_return_observations")
    stddev = statistics.stdev(returns)
    if stddev == 0:
        return _metric(None, "zero_return_variance")
    return _metric(round((statistics.mean(returns) / stddev) * math.sqrt(len(returns)), 4))


def _sortino(returns: list[float]) -> dict[str, Any]:
    if len(returns) < MIN_RETURN_OBSERVATIONS:
        return _metric(None, "fewer_than_2_return_observations")
    downside = [value for value in returns if value < 0]
    if not downside:
        return _metric(None, "no_downside_return_observations")
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside))
    if downside_deviation == 0:
        return _metric(None, "zero_downside_deviation")
    return _metric(round(statistics.mean(returns) / downside_deviation, 4))


def _planned_zone_metric(add_events: list[dict[str, Any]], fills: list[dict[str, Any]]) -> dict[str, Any]:
    fill_prices = [_float(fill.get("fill_price")) for fill in fills]
    fill_prices = [price for price in fill_prices if price is not None]
    zones = []
    for event in add_events:
        zone = event.get("planned_entry_zone")
        if isinstance(zone, (list, tuple)) and len(zone) == 2:
            low = _float(zone[0])
            high = _float(zone[1])
            if low is not None and high is not None:
                zones.append((low + high) / 2)
    if not fill_prices or not zones:
        return _metric(None, "planned_entry_zone_unavailable")
    average_entry = statistics.mean(fill_prices)
    average_zone = statistics.mean(zones)
    return _metric({
        "average_entry_price": round(average_entry, 6),
        "planned_zone_midpoint": round(average_zone, 6),
        "difference_percent": round(((average_entry - average_zone) / average_zone) * 100, 4) if average_zone else None,
    })


def _safe_accuracy(safe_labels: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not safe_labels:
        return _metric(None, "dca_safe_labels_unavailable")
    profitable = any(trade["net_pnl"] > 0 for trade in trades)
    correct = sum(1 for event in safe_labels if bool(event.get("dca_safe")) == profitable)
    return _metric(round(correct / len(safe_labels), 4))


def _max_drawdown(pnls: list[float]) -> tuple[float, float | None]:
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    max_dd_pct: float | None = 0.0
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown
            max_dd_pct = (drawdown / peak) * 100 if peak > 0 else None
    return max_dd, max_dd_pct


def _average_hold_hours(trades: list[dict[str, Any]]) -> float | None:
    durations = []
    for trade in trades:
        start = trade.get("start")
        end = trade.get("end")
        if start and end:
            durations.append((end - start).total_seconds() / 3600)
    return round(statistics.mean(durations), 2) if durations else None


def _average_exposure(trades: list[dict[str, Any]]) -> float:
    exposures = []
    for trade in trades:
        levels = {int(fill.get("level")) for fill in trade.get("fills", []) if _float(fill.get("level")) is not None}
        exposures.append(sum(ENTRY_ALLOCATIONS.get(level, 0.0) for level in levels))
    return statistics.mean(exposures) if exposures else 0.0


def _date_range(trades: list[dict[str, Any]]) -> dict[str, str | None]:
    if not trades:
        return {"start": None, "end": None}
    starts: list[datetime] = [trade["scan_start"] for trade in trades if isinstance(trade.get("scan_start"), datetime)]
    ends: list[datetime] = [trade["end"] for trade in trades if isinstance(trade.get("end"), datetime)]
    return {
        "start": _iso(min(starts)) if starts else None,
        "end": _iso(max(ends)) if ends else None,
    }


def _insufficient_reasons(coverages: list[dict[str, Any]], trades: list[dict[str, Any]]) -> list[str]:
    if trades:
        return []
    reasons = []
    for coverage in coverages:
        if coverage.get("status") == "insufficient_history":
            reasons.append("insufficient_history")
        for skipped in coverage.get("skipped_scans") or []:
            reason = skipped.get("reason")
            if reason:
                reasons.append(str(reason))
    return sorted(set(reasons)) or ["fewer_than_1_reconstructed_trades"]


def _benchmark_unavailable() -> dict[str, Any]:
    return {
        "value": None,
        "reason": "benchmark_price_history_unavailable_from_reconstruction",
    }


def _metric(value: Any, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "reason": reason}


def _float(value: Any) -> float | None:
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


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


def _min_text(values: Any) -> str | None:
    present = [value for value in values if value]
    return min(present) if present else None


def _max_text(values: Any) -> str | None:
    present = [value for value in values if value]
    return max(present) if present else None
