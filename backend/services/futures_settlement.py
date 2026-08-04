"""Settlement-asset selection for futures account truth (Phase 3.1).

MEXC returns many dust wallets (STETH, SHIB, …) before USDT. Always prefer a
meaningful settlement currency for snapshots and account-return series.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, TypeVar

# Prefer stables in this order when equities are comparable.
PREFERRED_SETTLEMENT_ASSETS = ("USDT", "USDC", "USD", "BUSD")
_EQUITY_EPS = 1e-8

T = TypeVar("T")


def _asset_code(raw: Dict[str, Any]) -> str:
    return str(raw.get("currency") or raw.get("asset") or raw.get("settlement_asset") or "USDT").upper()


def _pref_rank(asset: str) -> int:
    try:
        return PREFERRED_SETTLEMENT_ASSETS.index(asset)
    except ValueError:
        return len(PREFERRED_SETTLEMENT_ASSETS) + 1


def select_primary_futures_raw(assets: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick one raw MEXC account-asset row for the primary snapshot.

    Rules:
    1. Prefer non-zero |equity| over pure dust zeros.
    2. Among those, prefer preferred stables (USDT first).
    3. Then higher |equity|.
    4. If everything is zero, still prefer USDT/USDC if present (stable primary).
    """
    if not assets:
        return None
    scored: List[tuple] = []
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        asset = _asset_code(raw)
        try:
            equity = abs(float(raw.get("equity") if raw.get("equity") is not None else 0.0))
        except (TypeError, ValueError):
            equity = 0.0
        nonzero = 0 if equity > _EQUITY_EPS else 1
        scored.append((nonzero, _pref_rank(asset), -equity, asset, raw))
    if not scored:
        return None
    scored.sort()
    return scored[0][4]


def choose_settlement_asset_for_series(
    assets: Iterable[str],
    peak_abs_equity: Dict[str, float],
) -> Optional[str]:
    """Choose which settlement series to use for account-return history."""
    best: Optional[str] = None
    best_key: Optional[tuple] = None
    for asset in assets:
        peak = float(peak_abs_equity.get(asset) or 0.0)
        nonzero = 0 if peak > _EQUITY_EPS else 1
        key = (nonzero, _pref_rank(asset), -peak, asset)
        if best_key is None or key < best_key:
            best_key = key
            best = asset
    return best


def pick_opening_ending_snapshots(
    series: Sequence[T],
    *,
    equity_of,
    ts_of,
    id_of,
) -> Optional[tuple[T, T]]:
    """From a chronological series, pick opening/ending for return.

    Prefer first non-zero equity as opening and last snapshot as ending when
    both times differ. Falls back to first/last of the full series.
    """
    if len(series) < 2:
        return None
    ordered = sorted(series, key=lambda s: (ts_of(s), id_of(s)))
    nonzero = []
    for s in ordered:
        try:
            eq = equity_of(s)
            if eq is not None and abs(float(eq)) > _EQUITY_EPS:
                nonzero.append(s)
        except (TypeError, ValueError):
            continue
    if len(nonzero) >= 2:
        opening, ending = nonzero[0], ordered[-1]
        # If last is still zero but we have non-zero history, use last non-zero as end.
        try:
            if abs(float(equity_of(ending) or 0.0)) <= _EQUITY_EPS:
                ending = nonzero[-1]
        except (TypeError, ValueError):
            ending = nonzero[-1]
        if ts_of(opening) < ts_of(ending) or id_of(opening) != id_of(ending):
            return opening, ending
        return None
    if len(nonzero) == 1:
        opening = nonzero[0]
        ending = ordered[-1]
        if id_of(opening) == id_of(ending) and len(ordered) >= 2:
            # only one non-zero point — need a distinct end
            for s in reversed(ordered):
                if id_of(s) != id_of(opening):
                    ending = s
                    break
        if id_of(opening) != id_of(ending) or ts_of(opening) != ts_of(ending):
            return opening, ending
        return None
    # all zero / null — still return endpoints so caller can emit futures_equity_flat
    return ordered[0], ordered[-1]
