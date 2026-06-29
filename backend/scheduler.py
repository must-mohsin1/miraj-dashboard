"""APScheduler integration — periodic scan of all active watchlist pairs.

Every 4 hours the scheduler fetches every user's watchlist, runs the full
analysis pipeline for each unique pair, then writes results to the ``analyses``
table for every user who watches that pair.  After persisting results, the
alert manager evaluates thresholds and delivers alerts.  Each cycle is tracked
in ``scan_runs`` with status tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from backend.database import get_session_factory
from backend.models import Analysis, ScanRun, WatchlistPair
from backend.obsidian import get_vault_path, is_sync_enabled, sync_scan_result
from backend.services.analysis_service import run_scan

logger = logging.getLogger(__name__)

# ── Scheduler singleton ──────────────────────────────────────────────────
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Return the singleton AsyncIOScheduler, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


# ── The scheduled job ────────────────────────────────────────────────────


async def run_scheduled_scan() -> None:
    """Iterate over all users' active watchlist pairs and run analysis.

    This is the APScheduler job callback.  It:
      1. Creates a ScanRun record with status='running'.
      2. Queries all WatchlistPair rows, grouped by pair.
      3. Runs ``run_scan`` on each distinct unique pair.
      4. Writes an ``Analysis`` row for **every** user who watches that pair.
      5. Passes results to the alert manager for threshold/dedup/channel routing.
      6. Marks the ScanRun as completed (or failed) with pair count / error.

    Logging includes start/end time, pair count, and alert outcomes.
    """
    logger.info("Scheduled scan: starting")

    factory = get_session_factory()
    async with factory() as session:
        # ── Create scan run record ──────────────────────────────────
        scan_run = ScanRun(
            started_at=datetime.now(timezone.utc),
            status="running",
            pair_count=0,
        )
        session.add(scan_run)
        await session.flush()
        scan_run_id = scan_run.id

        try:
            # ── Fetch all watchlist pairs ────────────────────────────
            result = await session.execute(
                select(WatchlistPair).order_by(WatchlistPair.user_id)
            )
            watchlist_pairs = result.scalars().all()

            if not watchlist_pairs:
                logger.info("Scheduled scan: no watchlist pairs found; nothing to do")
                scan_run.status = "completed"
                scan_run.ended_at = datetime.now(timezone.utc)
                scan_run.pair_count = 0
                await session.commit()
                return

            # Build two maps:
            #   pair_to_users  : pair → list of user_ids who watch it
            #   unique_pairs   : ordered list of distinct pair symbols
            pair_to_users: dict[str, list[int]] = {}
            for wp in watchlist_pairs:
                pair = wp.pair.strip().upper()
                pair_to_users.setdefault(pair, []).append(wp.user_id)
            unique_pairs = list(pair_to_users.keys())

            logger.info(
                "Scheduled scan: %d total rows, %d unique pairs to scan",
                len(watchlist_pairs),
                len(unique_pairs),
            )

            # ── Run each unique pair scan once ───────────────────────
            errors: list[str] = []
            success_count = 0
            scan_results_map: dict[str, dict[str, Any]] = {}  # pair → result

            for pair in unique_pairs:
                try:
                    # Run the pipeline in a thread (it's synchronous)
                    scan_result = await asyncio.to_thread(run_scan, pair)
                    scan_results_map[pair] = scan_result
                    success_count += 1
                except Exception as exc:
                    logger.error(
                        "Scheduled scan failed for pair %s: %s", pair, exc,
                    )
                    errors.append(f"{pair}: {exc}")

            # ── Persist results for each user who watches the pair ───
            results_by_user: dict[int, list[dict[str, Any]]] = {}

            for pair, users in pair_to_users.items():
                scan_result = scan_results_map.get(pair)
                for user_id in users:
                    if scan_result is None:
                        continue  # scan failed for this pair
                    # Persist
                    score_val: float | None = (
                        scan_result.get("overall_score") or scan_result.get("confluence_score")
                    )
                    analysis = Analysis(
                        user_id=user_id,
                        pair=pair,
                        analysis_type="scheduled_scan",
                        score=score_val,
                        parameters=json.dumps({"symbol": pair}),
                        result=json.dumps({
                            "confluence_score": scan_result.get("confluence_score"),
                            "trade_plan": scan_result.get("trade_plan"),
                            "score_breakdown": scan_result.get("score_breakdown"),
                        }),
                    )
                    session.add(analysis)

                    # ── Obsidian vault sync (best-effort) ─────────────
                    try:
                        vault_path = await get_vault_path(session, user_id)
                        if vault_path:
                            enabled = await is_sync_enabled(session, user_id, pair)
                            if enabled:
                                await asyncio.to_thread(
                                    sync_scan_result,
                                    user_id, pair, scan_result, vault_path,
                                )
                    except Exception as sync_exc:
                        logger.warning(
                            "Obsidian sync failed for %s (user %d): %s",
                            pair, user_id, sync_exc,
                        )

                    # Add to per-user results for alert manager
                    results_by_user.setdefault(user_id, []).append(scan_result)

            # ── Run alert manager ────────────────────────────────────
            if results_by_user:
                try:
                    from backend.alerts.manager import process_scan_results

                    alert_outcomes = await process_scan_results(session, results_by_user)
                    sent_count = sum(
                        1 for o in alert_outcomes if o and o.get("status") == "sent"
                    )
                    logger.info(
                        "Alert manager: %d alerts sent out of %d evaluated",
                        sent_count, len(alert_outcomes),
                    )
                except Exception as exc:
                    logger.exception("Alert manager failed: %s", exc)

            # ── Finalise scan run ────────────────────────────────────
            total_scanned = len(unique_pairs)
            if errors:
                error_msg = "; ".join(errors[:5])
                if len(errors) > 5:
                    error_msg += f" (+{len(errors) - 5} more)"
                scan_run.status = "failed" if success_count == 0 else "completed"
                scan_run.error_message = error_msg
            else:
                scan_run.status = "completed"

            scan_run.pair_count = total_scanned
            scan_run.ended_at = datetime.now(timezone.utc)
            await session.commit()

            logger.info(
                "Scheduled scan: completed — %d/%d successful, errors=%d, scan_run=%d",
                success_count,
                total_scanned,
                len(errors),
                scan_run_id,
            )

        except Exception as exc:
            # Unexpected error — mark run as failed
            scan_run.status = "failed"
            scan_run.error_message = str(exc)
            scan_run.ended_at = datetime.now(timezone.utc)
            await session.commit()
            logger.exception("Scheduled scan: unexpected failure (scan_run=%d)", scan_run_id)


# ── Lifecycle helpers ──────────────────────────────────────────────────────


def setup_scheduler(app) -> AsyncIOScheduler:
    """Configure the scheduler, attach the 4-hour scan and daily digest jobs.

    Call once at application startup (inside the lifespan context).
    """
    scheduler = get_scheduler()
    scheduler.add_job(
        run_scheduled_scan,
        trigger=CronTrigger(hour="*/4"),  # every 4 hours
        id="watchlist_scan",
        name="Watchlist scan (every 4h)",
        replace_existing=True,
    )
    # Register the daily digest job
    from backend.alerts.digest import register_digest_job

    register_digest_job(scheduler)
    return scheduler


def start_scheduler() -> None:
    """Start the APScheduler if it isn't already running."""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started")


def stop_scheduler() -> None:
    """Shut down the APScheduler gracefully."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
        _scheduler = None
