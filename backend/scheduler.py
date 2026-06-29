"""APScheduler integration — periodic scan of all active watchlist pairs.

Every 4 hours the scheduler fetches every user's watchlist, runs the full
analysis pipeline for each pair, and writes results to the ``analyses``
table.  Each cycle is tracked in ``scan_runs`` with status tracking.
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
      2. Queries all WatchlistPair rows.
      3. Runs ``run_scan`` on each distinct pair (deduplicated).
      4. Writes results to the ``analyses`` table.
      5. Marks the ScanRun as completed (or failed) with pair count / error.

    Logging includes start/end time and pair count.
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

            # Deduplicate pairs across users (run scan once per symbol)
            seen_pairs: set[str] = set()
            unique_pairs: list[tuple[int, str]] = []  # (user_id, pair)
            for wp in watchlist_pairs:
                pair = wp.pair.strip().upper()
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    unique_pairs.append((wp.user_id, pair))

            logger.info(
                "Scheduled scan: %d total rows, %d unique (user, pair) pairs to scan",
                len(watchlist_pairs),
                len(unique_pairs),
            )

            errors: list[str] = []
            success_count = 0

            for user_id, pair in unique_pairs:
                try:
                    # Run the pipeline in a thread (it's synchronous)
                    scan_result = await asyncio.to_thread(run_scan, pair)

                    # Persist result to analyses table
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
                    success_count += 1
                except Exception as exc:
                    logger.error(
                        "Scheduled scan failed for pair %s (user %d): %s",
                        pair, user_id, exc,
                    )
                    errors.append(f"{pair}: {exc}")

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
    """Configure the scheduler, attach the 4-hour cron job, and wire lifespan.

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
