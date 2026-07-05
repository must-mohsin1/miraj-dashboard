"""Diff service — compare two scan result dicts and emit signal changes.

Pure functions.  Each comparator returns a list of ``ScanDiffEntry`` dicts
(empty if nothing changed).  The orchestrator ``diff_scans`` concatenates
them.

Backward compatibility
----------------------
Old analysis rows (pre-A0) only stored ``{confluence_score, trade_plan,
score_breakdown}``.  When diffing against such a row, the comparator for
missing fields silently emits nothing (via ``_safe_get`` returning ``None``
where a JSON path is absent) — but score / trade_plan diffs still work.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

# ── Severity constants ────────────────────────────────────────────────────

Severity = Literal["major", "minor", "info"]

# ── Config thresholds (kept here for easy tuning) ──────────────────────────

SCORE_MAJOR_DELTA: float = 5.0      # total score change > 5 → major
SCORE_MINOR_DELTA: float = 1.0      # total score change 1–5 → minor
CATEGORY_MINOR_DELTA: float = 2.0   # per-category change ≥ 2 → minor
PRICE_NOISE_EPSILON: float = 0.01   # ignore sub-cent price moves

# Pattern names whose appearance / invalidation is "high impact" → major.
HIGH_IMPACT_PATTERNS: frozenset[str] = frozenset({
    "double_top",
    "double_bottom",
    "head_and_shoulders",
    "inverse_head_and_shoulders",
})

# Green-ish and red-ish QQE signal sets (for the bull/bear flip test).
_GREEN_SIGNALS: frozenset[str] = frozenset({"GREEN", "GREEN-STRONG"})
_RED_SIGNALS: frozenset[str] = frozenset({"RED", "RED-STRONG"})

# Timeframes we iterate over for QQE / structure / indicator diffs.
QQE_TIMEFRAMES: tuple[str, ...] = ("daily", "4h", "1h")
STRUCTURE_TIMEFRAMES: tuple[str, ...] = ("weekly", "daily", "4h", "1h", "15m")
INDICATOR_TIMEFRAMES: tuple[str, ...] = ("daily", "4h")

# The 5 confluence-score categories that ``scores`` dict carries.
CATEGORY_KEYS: tuple[str, ...] = (
    "regime", "location", "confirmation", "volume_retest", "risk",
)


# ── Public entry / dataclass ──────────────────────────────────────────────


def diff_scans(
    prev: dict[str, Any],
    cur: dict[str, Any],
    prev_ts: datetime,
    cur_ts: datetime,
) -> list[dict[str, Any]]:
    """Diff two scan result dicts and return a list of change entries.

    Parameters
    ----------
    prev : dict
        The older scan's full result JSON (parsed).
    cur : dict
        The newer scan's full result JSON (parsed).
    prev_ts, cur_ts : datetime
        The ``created_at`` timestamps of the two scans.  Entry ``timestamp``
        is the ISO-8601 string of the *newer* scan (the one that changed).

    Returns
    -------
    list[dict]
        Each dict has keys: ``field``, ``change``, ``severity``,
        ``old_value``, ``new_value``, ``timestamp``.
    """
    ts_iso = cur_ts.isoformat() if isinstance(cur_ts, datetime) else str(cur_ts)

    entries: list[dict[str, Any]] = []
    entries += diff_score(prev, cur, ts_iso)
    entries += diff_qqe_signals(prev, cur, ts_iso)
    entries += diff_structure(prev, cur, ts_iso)
    entries += diff_trade_plan(prev, cur, ts_iso)
    entries += diff_patterns(prev, cur, ts_iso)
    entries += diff_indicators(prev, cur, ts_iso)
    return entries


def summarise(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Return ``{major: N, minor: N, info: N}`` counts for *entries*."""
    summary: dict[str, int] = {"major": 0, "minor": 0, "info": 0}
    for e in entries:
        sev = e.get("severity", "info")
        if sev in summary:
            summary[sev] += 1
    return summary


# ── Dotted-path helper ────────────────────────────────────────────────────


def _safe_get(d: Any, path: str, default: Any = None) -> Any:
    """Dotted-path getter.  Returns ``default`` when any key is missing.

    Examples
    --------
    >>> _safe_get({"a": {"b": 1}}, "a.b")
    1
    >>> _safe_get({"a": {}}, "a.b")
    None
    >>> _safe_get(None, "a.b")
    None
    """
    if d is None:
        return default
    cur: Any = d
    for key in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
        if cur is None:
            return default
    return cur


def _entry(
    field: str,
    change: str,
    severity: Severity,
    old_value: Any,
    new_value: Any,
    ts_iso: str,
) -> dict[str, Any]:
    """Build a single change-entry dict."""
    return {
        "field": field,
        "change": change,
        "severity": severity,
        "old_value": _jsonable(old_value),
        "new_value": _jsonable(new_value),
        "timestamp": ts_iso,
    }


def _jsonable(v: Any) -> Any:
    """Coerce numpy / non-natively-serialisable values to plain Python."""
    if v is None:
        return None
    # numpy scalars expose ``.item()``
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:  # pragma: no cover — defensive
            pass
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (str, int, bool)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def _fmt_num(v: Any, dp: int = 1) -> str:
    try:
        return f"{float(v):.{dp}f}"
    except (TypeError, ValueError):
        return "—"


# ── 1.3.1  diff_score ─────────────────────────────────────────────────────


def diff_score(prev: dict[str, Any], cur: dict[str, Any], ts_iso: str) -> list[dict[str, Any]]:
    """Compare the confluence score (total + per-category)."""
    out: list[dict[str, Any]] = []
    prev_total = _safe_get(prev, "confluence_score")
    cur_total = _safe_get(cur, "confluence_score")
    if prev_total is not None and cur_total is not None:
        try:
            delta = float(cur_total) - float(prev_total)
        except (TypeError, ValueError):
            delta = 0.0
        if abs(delta) >= 0.05:  # ignore sub-rounding noise
            arrow = "▲" if delta > 0 else "▼"
            sev: Severity = (
                "major" if abs(delta) > SCORE_MAJOR_DELTA
                else "minor" if abs(delta) >= SCORE_MINOR_DELTA
                else "info"
            )
            out.append(_entry(
                field="score.total",
                change=f"{_fmt_num(prev_total)} → {_fmt_num(cur_total)} ({arrow} {abs(delta):.1f})",
                severity=sev,
                old_value=prev_total,
                new_value=cur_total,
                ts_iso=ts_iso,
            ))

    # Per-category scores (in the ``scores`` dict)
    for cat in CATEGORY_KEYS:
        prev_cat = _safe_get(prev, f"scores.{cat}")
        cur_cat = _safe_get(cur, f"scores.{cat}")
        if prev_cat is None or cur_cat is None:
            continue
        try:
            cdelta = float(cur_cat) - float(prev_cat)
        except (TypeError, ValueError):
            continue
        if abs(cdelta) >= 0.5:  # ignore rounding noise
            arrow = "▲" if cdelta > 0 else "▼"
            sev = "minor" if abs(cdelta) >= CATEGORY_MINOR_DELTA else "info"
            out.append(_entry(
                field=f"score.{cat}",
                change=f"{_fmt_num(prev_cat)} → {_fmt_num(cur_cat)} ({arrow} {abs(cdelta):.1f})",
                severity=sev,
                old_value=prev_cat,
                new_value=cur_cat,
                ts_iso=ts_iso,
            ))
    return out


# ── 1.3.2  diff_qqe_signals ──────────────────────────────────────────────


def diff_qqe_signals(prev: dict[str, Any], cur: dict[str, Any], ts_iso: str) -> list[dict[str, Any]]:
    """Compare per-timeframe QQE signals.

    Source rows store the signal under ``qqe[tf]["signal"]`` ∈
    {GREEN-STRONG, GREEN, RED-STRONG, RED, Neutral}.  Some rows also have
    a summarised ``qqe_signals[tf]`` dict but the raw ``qqe`` payload is
    what we diff — it carries the actual enum.
    """
    out: list[dict[str, Any]] = []
    for tf in QQE_TIMEFRAMES:
        prev_sig = _safe_get(prev, f"qqe.{tf}.signal")
        cur_sig = _safe_get(cur, f"qqe.{tf}.signal")
        if prev_sig is None or cur_sig is None:
            continue
        if str(prev_sig) == str(cur_sig):
            continue
        out.append(_entry(
            field=f"qqe_signals.{tf}",
            change=f"{prev_sig} → {cur_sig}",
            severity=_qqe_severity(prev_sig, cur_sig),
            old_value=prev_sig,
            new_value=cur_sig,
            ts_iso=ts_iso,
        ))
    return out


def _qqe_severity(prev: str, cur: str) -> Severity:
    """Severity for a QQE signal change.

    - GREEN-ish → RED-ish or reverse (true bull/bear flip) → major
    - same-side strength change (GREEN ↔ GREEN-STRONG) → minor
    - anything → Neutral → minor
    """
    p = str(prev)
    c = str(cur)
    if p in _GREEN_SIGNALS and c in _RED_SIGNALS:
        return "major"
    if p in _RED_SIGNALS and c in _GREEN_SIGNALS:
        return "major"
    return "minor"


# ── 1.3.3  diff_structure ────────────────────────────────────────────────


def diff_structure(prev: dict[str, Any], cur: dict[str, Any], ts_iso: str) -> list[dict[str, Any]]:
    """Compare per-timeframe market-structure labels (HH/HL/LH/LL).

    Any structure-label change is a major event (trend character shift).
    If the ``structure`` field is absent in either row (old pre-A0 data),
    emit nothing for that timeframe.
    """
    out: list[dict[str, Any]] = []
    for tf in STRUCTURE_TIMEFRAMES:
        # structure is a dict keyed by tf with ``label`` inside
        prev_label = _safe_get(prev, f"structure.{tf}.label")
        cur_label = _safe_get(cur, f"structure.{tf}.label")
        if prev_label is None or cur_label is None:
            continue
        if str(prev_label) == str(cur_label):
            continue
        out.append(_entry(
            field=f"structure.{tf}",
            change=f"{prev_label} → {cur_label}",
            severity="major",
            old_value=prev_label,
            new_value=cur_label,
            ts_iso=ts_iso,
        ))
    return out


# ── 1.3.4  diff_trade_plan ───────────────────────────────────────────────


def diff_trade_plan(prev: dict[str, Any], cur: dict[str, Any], ts_iso: str) -> list[dict[str, Any]]:
    """Compare trade_plan (direction, trade_decision, entry, stop, targets)."""
    out: list[dict[str, Any]] = []

    # Direction change → major
    prev_dir = _safe_get(prev, "trade_plan_flat.direction") or _safe_get(prev, "trade_plan.direction")
    cur_dir = _safe_get(cur, "trade_plan_flat.direction") or _safe_get(cur, "trade_plan.direction")
    if prev_dir and cur_dir and str(prev_dir).upper() != str(cur_dir).upper():
        out.append(_entry(
            field="trade_plan.direction",
            change=f"{prev_dir} → {cur_dir}",
            severity="major",
            old_value=prev_dir,
            new_value=cur_dir,
            ts_iso=ts_iso,
        ))

    # trade_decision flip (True → False or reverse) → major
    prev_td = _safe_get(prev, "trade_plan.trade_decision")
    cur_td = _safe_get(cur, "trade_plan.trade_decision")
    if prev_td is not None and cur_td is not None and bool(prev_td) != bool(cur_td):
        out.append(_entry(
            field="trade_plan.trade_decision",
            change=f"{bool(prev_td)} → {bool(cur_td)}",
            severity="major",
            old_value=bool(prev_td),
            new_value=bool(cur_td),
            ts_iso=ts_iso,
        ))

    # Numeric price-level changes → minor
    for field_path, label in (
        ("trade_plan_flat.entry", "trade_plan.entry"),
        ("trade_plan_flat.stop_loss", "trade_plan.stop_loss"),
        ("trade_plan_flat.target_1", "trade_plan.target_1"),
        ("trade_plan_flat.target_2", "trade_plan.target_2"),
        ("trade_plan_flat.target_3", "trade_plan.target_3"),
    ):
        prev_val = _safe_get(prev, field_path)
        cur_val = _safe_get(cur, field_path)
        if prev_val is None and cur_val is None:
            continue
        try:
            if prev_val is not None and cur_val is not None:
                diff = abs(float(cur_val) - float(prev_val))
                if diff < PRICE_NOISE_EPSILON:
                    continue
        except (TypeError, ValueError):
            continue
        out.append(_entry(
            field=label,
            change=f"{_fmt_num(prev_val, 2)} → {_fmt_num(cur_val, 2)}",
            severity="minor",
            old_value=prev_val,
            new_value=cur_val,
            ts_iso=ts_iso,
        ))
    return out


# ── 1.3.5  diff_patterns ─────────────────────────────────────────────────


def _pattern_key(p: Any) -> Optional[str]:
    """Extract a stable identifier from a pattern dict.

    Pattern detectors in ``mirai_core/patterns.py`` emit dicts with either a
    ``"pattern"`` key (e.g. "Double Top") or a ``"type"`` key.  We normalise
    to lowercase-snake for matching against the high-impact set.
    """
    if not isinstance(p, dict):
        return None
    name = p.get("pattern") or p.get("name") or p.get("type")
    if not name:
        return None
    return str(name).lower().replace(" ", "_")


def diff_patterns(prev: dict[str, Any], cur: dict[str, Any], ts_iso: str) -> list[dict[str, Any]]:
    """Compare detected patterns (new / invalidated / confirmation flips)."""
    out: list[dict[str, Any]] = []
    prev_list = _safe_get(prev, "patterns.detected", []) or []
    cur_list = _safe_get(cur, "patterns.detected", []) or []
    if not isinstance(prev_list, list):
        prev_list = []
    if not isinstance(cur_list, list):
        cur_list = []

    prev_map = {_pattern_key(p): p for p in prev_list if _pattern_key(p)}
    cur_map = {_pattern_key(p): p for p in cur_list if _pattern_key(p)}

    # New patterns (in cur, not in prev)
    for name, pat in cur_map.items():
        if name not in prev_map:
            confirmed = bool(pat.get("confirmed", False)) if isinstance(pat, dict) else False
            label = pat.get("pattern") or pat.get("name") or pat.get("type") or name
            sev: Severity = "major" if name in HIGH_IMPACT_PATTERNS else "minor"
            out.append(_entry(
                field="patterns.new",
                change=f"{label} ({'confirmed' if confirmed else 'unconfirmed'})",
                severity=sev,
                old_value=None,
                new_value=pat,
                ts_iso=ts_iso,
            ))

    # Invalidated patterns (in prev, not in cur)
    for name, pat in prev_map.items():
        if name not in cur_map:
            label = pat.get("pattern") or pat.get("name") or pat.get("type") or name
            sev = "major" if name in HIGH_IMPACT_PATTERNS else "minor"
            out.append(_entry(
                field="patterns.invalidated",
                change=f"{label}",
                severity=sev,
                old_value=pat,
                new_value=None,
                ts_iso=ts_iso,
            ))

    # Confirmation flips
    for name, cur_pat in cur_map.items():
        prev_pat = prev_map.get(name)
        if not prev_pat:
            continue
        prev_conf = bool(prev_pat.get("confirmed", False)) if isinstance(prev_pat, dict) else False
        cur_conf = bool(cur_pat.get("confirmed", False)) if isinstance(cur_pat, dict) else False
        if prev_conf == cur_conf:
            continue
        label = cur_pat.get("pattern") or cur_pat.get("name") or cur_pat.get("type") or name
        if not prev_conf and cur_conf:
            out.append(_entry(
                field="patterns.confirmed",
                change=f"{label} confirmed",
                severity="minor",
                old_value=prev_conf,
                new_value=cur_conf,
                ts_iso=ts_iso,
            ))
        else:
            out.append(_entry(
                field="patterns.unconfirmed",
                change=f"{label} no longer confirmed",
                severity="info",
                old_value=prev_conf,
                new_value=cur_conf,
                ts_iso=ts_iso,
            ))
    return out


# ── 1.3.6  diff_indicators ────────────────────────────────────────────────


def diff_indicators(prev: dict[str, Any], cur: dict[str, Any], ts_iso: str) -> list[dict[str, Any]]:
    """Compare per-TF indicators: EMA stack, BB squeeze, RSI cross."""
    out: list[dict[str, Any]] = []
    for tf in INDICATOR_TIMEFRAMES:
        # BB squeeze
        prev_sq = _safe_get(prev, f"indicators.{tf}.bb_squeeze")
        cur_sq = _safe_get(cur, f"indicators.{tf}.bb_squeeze")
        if prev_sq is not None and cur_sq is not None and bool(prev_sq) != bool(cur_sq):
            before = "squeezing" if bool(prev_sq) else "released"
            after = "squeezing" if bool(cur_sq) else "released"
            out.append(_entry(
                field=f"indicators.{tf}.bb_squeeze",
                change=f"{before} → {after}",
                severity="minor",
                old_value=bool(prev_sq),
                new_value=bool(cur_sq),
                ts_iso=ts_iso,
            ))

        # RSI crossing 30/70
        prev_rsi = _safe_get(prev, f"indicators.{tf}.rsi")
        cur_rsi = _safe_get(cur, f"indicators.{tf}.rsi")
        if prev_rsi is not None and cur_rsi is not None:
            try:
                p = float(prev_rsi)
                c = float(cur_rsi)
            except (TypeError, ValueError):
                p = c = None
            if p is not None and c is not None:
                crossed = None
                if p <= 30 < c:
                    crossed = "crossed above 30"
                elif p >= 70 > c:
                    crossed = "crossed below 70"
                elif p < 30 <= c or p > 70 >= c:
                    crossed = "crossed into neutral"

                if crossed:
                    # severity: crossing 30 up or 70 down → minor (entry/exit);
                    # entering the neutral band → info
                    sev: Severity = "info" if (
                        crossed == "crossed into neutral"
                    ) else "minor"
                    out.append(_entry(
                        field=f"indicators.{tf}.rsi",
                        change=f"{_fmt_num(p)} → {_fmt_num(c)} ({crossed})",
                        severity=sev,
                        old_value=p,
                        new_value=c,
                        ts_iso=ts_iso,
                    ))
                elif abs(c - p) >= 1.0:
                    # monotonic RSI drift within the 30–70 neutral band → info
                    out.append(_entry(
                        field=f"indicators.{tf}.rsi",
                        change=f"{_fmt_num(p)} → {_fmt_num(c)}",
                        severity="info",
                        old_value=p,
                        new_value=c,
                        ts_iso=ts_iso,
                    ))

        # EMA golden/death cross
        prev_cross = _safe_get(prev, f"indicators.{tf}.golden_death_cross")
        cur_cross = _safe_get(cur, f"indicators.{tf}.golden_death_cross")
        if prev_cross and cur_cross and str(prev_cross) != str(cur_cross):
            out.append(_entry(
                field=f"indicators.{tf}.ema_cross",
                change=f"{prev_cross} → {cur_cross}",
                severity="minor",
                old_value=prev_cross,
                new_value=cur_cross,
                ts_iso=ts_iso,
            ))

    return out
