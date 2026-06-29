"""Batch scan service — run the full analysis pipeline on multiple symbols in
parallel using ``ThreadPoolExecutor``, then sort by confluence_score descending.

Rate limiting
-------------
A user may trigger at most one batch scan every 5 minutes (configurable via
``BATCH_SCAN_COOLDOWN``).  The cooldown is tracked in-memory per user id.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from backend.services.analysis_service import run_scan

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
BATCH_SCAN_COOLDOWN: int = 300  # 5 minutes, in seconds
_MAX_WORKERS: int = 8

# ── In-memory rate-limit tracker ──────────────────────────────────────────
_last_batch_scan: dict[int, float] = {}  # user_id → timestamp of last batch scan


def can_run_batch(user_id: int) -> bool:
    """Return True if *user_id* is not in cooldown."""
    last = _last_batch_scan.get(user_id)
    if last is None:
        return True
    return (time.time() - last) > BATCH_SCAN_COOLDOWN


def mark_batch_run(user_id: int) -> None:
    """Record that *user_id* just ran a batch scan."""
    _last_batch_scan[user_id] = time.time()


def seconds_until_retry(user_id: int) -> int:
    """Seconds remaining before *user_id* can run another batch scan."""
    last = _last_batch_scan.get(user_id)
    if last is None:
        return 0
    remaining = BATCH_SCAN_COOLDOWN - (time.time() - last)
    return max(0, int(remaining))


def clear_rate_limit(user_id: int | None = None) -> None:
    """Clear rate-limit entry (for tests).  If *user_id* is None, clear all."""
    global _last_batch_scan
    if user_id is None:
        _last_batch_scan = {}
    else:
        _last_batch_scan.pop(user_id, None)


# ── Batch scan ──────────────────────────────────────────────────────────────


def run_batch_scan(pairs: list[str]) -> list[dict[str, Any]]:
    """Run the full pipeline for every symbol in *pairs* using a thread pool.

    Each symbol is submitted to ``ThreadPoolExecutor`` (max 8 workers).
    Individual failures produce a placeholder result with ``error`` set so
    the caller can still see which symbols failed.

    Returns a list of result dicts sorted by ``confluence_score`` descending
    (symbols with no score sort to the end).
    """
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        fut_to_symbol = {
            pool.submit(run_scan, symbol): symbol for symbol in pairs
        }

        for future in as_completed(fut_to_symbol):
            symbol = fut_to_symbol[future]
            try:
                data = future.result()
                results.append(data)
            except Exception as exc:
                logger.error("Batch scan failed for %s: %s", symbol, exc)
                errors.append({
                    "symbol": symbol,
                    "error": str(exc),
                    "confluence_score": 0.0,
                    "trade_plan": {"trade_decision": False, "error": str(exc)},
                    "score_breakdown": {},
                    "stale": False,
                    "cached_at": None,
                })

    # Sort successful results by confluence_score desc
    results.sort(key=lambda r: r.get("confluence_score", 0.0), reverse=True)

    # Append errors at the end (already score 0)
    results.extend(errors)

    return results
