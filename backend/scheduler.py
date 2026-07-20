"""APScheduler integration — periodic background jobs.

Three recurring jobs:
  1. **Watchlist scan** (every 4 h) — fetches every user's watchlist, runs the
     full analysis pipeline for each unique pair, writes results to ``analyses``,
     then invokes the alert manager.
  2. **Price alert check** (every 2 m) — evaluates active price alerts.
  3. **Portfolio auto-refresh** (every 5 m) — finds all connected users (rows in
     ``exchange_keys``) and refreshes their cached balances/positions/trades by
     calling the exchange service directly (no HTTP auth overhead). Keeps PnL
     current without the user clicking Refresh.
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
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session_factory
from backend.models import Analysis, ExchangeKey, PriceAlert, ScanRun, WatchlistPair
from backend.obsidian import get_vault_path, is_sync_enabled, sync_scan_result
from backend.services.analysis_service import build_persistable_result, run_scan

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
                if scan_result is None:
                    continue  # scan failed for this pair

                # Persist the same full normalized result the manual scan
                # route stores (trimmed of chart series) so diff_service can
                # compare QQE flips, structure changes, and verdict
                # transitions across scheduled scans too.  Serialised once
                # per pair and reused for every user who watches it.
                score_val: float | None = (
                    scan_result.get("overall_score") or scan_result.get("confluence_score")
                )
                result_json = json.dumps(
                    build_persistable_result(scan_result), default=str,
                )

                for user_id in users:
                    analysis = Analysis(
                        user_id=user_id,
                        pair=pair,
                        analysis_type="scheduled_scan",
                        score=score_val,
                        parameters=json.dumps({"symbol": pair}),
                        result=result_json,
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


# ── Price alert check job ──────────────────────────────────────────────────


async def _check_price_alerts_job() -> None:
    """APScheduler job callback — check all active price alerts.

    Fetches current prices for all symbols with active alerts, triggers
    those whose level has been hit, and sends notifications via the user's
    enabled alert channels.
    """
    logger.info("Price alert check: starting")
    factory = get_session_factory()
    async with factory() as session:
        try:
            from backend.services.price_alert_service import check_price_alerts
            outcomes = await check_price_alerts(session)
            triggered = [o for o in outcomes if o.get("status") == "triggered"]
            logger.info(
                "Price alert check: %d triggered out of %d checked",
                len(triggered), len(outcomes),
            )
        except Exception as exc:
            logger.exception("Price alert check failed: %s", exc)


# ── Portfolio auto-refresh job ──────────────────────────────────────────────


async def refresh_all_portfolios_job() -> None:
    """APScheduler job callback — refresh cached portfolio data for every
    connected user on every supported exchange.

    Designed to run every 5 minutes.  For each ``(user_id, exchange)`` row in
    ``exchange_keys`` it:

      1. Opens a dedicated DB session (independent of any HTTP request).
      2. Calls ``get_exchange()`` to build a ccxt instance from the stored
         encrypted keys — *no HTTP round-trip / JWT auth overhead*.
      3. Calls ``fetch_portfolio()`` to pull fresh balances / positions / trades.
      4. Persists results via the existing ``_persist_portfolio_data`` helper
         (same code path as the manual ``POST /refresh`` endpoint).

    Resilience:
      * **No connected users** → logs and returns immediately (skips entirely).
      * **Rate limits** → each user is refreshed at most once per 5-min cycle
        (the cron interval is the natural throttle); per-user failures are
        caught so one user being rate-limited doesn't skip others.
      * **Errors** → logged and the job continues to the next user/exchange;
        a top-level ``except`` guarantees the scheduler is never crashed.
    """
    logger.info("Portfolio auto-refresh: starting cycle")

    # Import here to avoid a circular import at module load time
    # (portfolio.py imports from exchange_service and models).
    from backend.routes.portfolio import _persist_portfolio_data
    from backend.services.exchange_service import (
        ExchangeError,
        ExchangeRateLimitError,
        fetch_portfolio,
        get_exchange,
        is_ccxt_available,
    )

    # Skip entirely if ccxt isn't installed (e.g. lightweight deploy).
    if not is_ccxt_available():
        logger.info("Portfolio auto-refresh: ccxt not installed — skipping")
        return

    factory = get_session_factory()
    async with factory() as session:
        # ── Find every connected (user, exchange) pair ────────────────
        result = await session.execute(select(ExchangeKey))
        key_rows = result.scalars().all()

        if not key_rows:
            logger.info("Portfolio auto-refresh: no connected users — skipping")
            return

        logger.info(
            "Portfolio auto-refresh: refreshing %d user/exchange connection(s)",
            len(key_rows),
        )

        success_count = 0
        skip_count = 0
        fail_count = 0

        # Process sequentially — MEXC/etc. rate limits are per-user, but a
        # single ccxt instance per user already enablesRateLimit. Processing
        # one at a time keeps the outbound request rate modest and the logs
        # easy to follow.
        for row in key_rows:
            user_id = row.user_id
            exchange_slug = row.exchange
            label = f"user {user_id} / {exchange_slug}"

            try:
                exchange_instance = await get_exchange(
                    user_id=user_id,
                    exchange_name=exchange_slug,
                    db_session=session,
                )
                data = await fetch_portfolio(
                    exchange_instance=exchange_instance,
                    user_id=user_id,
                )
                await _persist_portfolio_data(
                    session, user_id, exchange_slug, data, datetime.utcnow()
                )
                await session.commit()
                success_count += 1
                logger.info(
                    "Portfolio auto-refresh: refreshed %s "
                    "(%d balances, %d positions, %d trades)",
                    label,
                    len(data["balances"]),
                    len(data["positions"]),
                    len(data["trades"]),
                )
            except ExchangeRateLimitError as exc:
                # Rate-limited by the exchange — log and move on; the 5-min
                # cron interval ensures we don't hammer the API (≤1 refresh
                # per user per cycle).
                # Roll back any partial state for this user before continuing.
                await session.rollback()
                skip_count += 1
                logger.warning(
                    "Portfolio auto-refresh: rate-limited for %s — skipping: %s",
                    label, exc,
                )
            except ExchangeError as exc:
                await session.rollback()
                fail_count += 1
                logger.warning(
                    "Portfolio auto-refresh: exchange error for %s — skipping: %s",
                    label, exc,
                )
            except Exception as exc:
                await session.rollback()
                fail_count += 1
                logger.exception(
                    "Portfolio auto-refresh: unexpected error for %s: %s",
                    label, exc,
                )

        logger.info(
            "Portfolio auto-refresh: cycle complete — %d ok, %d skipped, %d failed",
            success_count, skip_count, fail_count,
        )


# ── Advanced alerts (RSI / EMA cross / volume spike) ────────────────────────


def select_advanced_signals(
    signals: list[dict[str, Any]], active_alert_types: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """Match detector output only to alert types configured for this symbol."""
    selected: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        signal_type = str(signal.get("type", ""))
        if signal_type.startswith("rsi") and "rsi" in active_alert_types:
            selected.setdefault("rsi", []).append(signal)
        elif signal_type.startswith("ema_cross") and "ema_cross" in active_alert_types:
            selected.setdefault("ema_cross", []).append(signal)
        elif signal_type == "volume_spike" and "volume_spike" in active_alert_types:
            selected.setdefault("volume_spike", []).append(signal)
    return selected


async def check_advanced_alerts_job() -> None:
    """APScheduler job callback — check advanced technical-signal alerts.

    For every user who has an active ``rsi``, ``ema_cross``, or
    ``volume_spike`` price alert, fetches the latest candles for the alert's
    symbol, runs the signal detectors, and when a signal is detected:
      1. Updates the alert's ``current_price`` with the last close.
      2. Sends a notification via the user's enabled alert channels.
      3. Marks the alert as triggered (with cooldown dedup).

    Designed to run every 5 minutes. Candles are fetched from a public
    exchange (no API keys needed for OHLCV).
    """
    logger.info("Advanced alert check: starting")

    from backend.services.signal_detector import (
        detect_all_signals,
        detect_ema_cross,
        detect_rsi_signals,
        detect_volume_spike,
    )
    from backend.models import WatchlistPair

    factory = get_session_factory()
    async with factory() as session:
        try:
            # Find all active advanced alerts (non-price types).
            result = await session.execute(
                select(PriceAlert).where(
                    PriceAlert.status == "active",
                    PriceAlert.alert_type.in_(
                        ["rsi", "ema_cross", "volume_spike"],
                    ),
                )
            )
            alerts = list(result.scalars().all())

            if not alerts:
                logger.debug("Advanced alert check: no active advanced alerts")
                return

            logger.info(
                "Advanced alert check: %d active advanced alerts", len(alerts),
            )

            # Group by symbol to avoid redundant candle fetches.
            from collections import defaultdict

            by_symbol: dict[str, list[PriceAlert]] = defaultdict(list)
            for alert in alerts:
                by_symbol[alert.symbol].append(alert)

            # Get a public exchange instance for fetching OHLCV.
            from backend.services.exchange_service import is_ccxt_available

            if not is_ccxt_available():
                logger.info("Advanced alert check: ccxt not installed — skipping")
                return

            import ccxt  # noqa: PLC0415

            public_exchange = ccxt.binance({"enableRateLimit": True})

            import asyncio as _asyncio

            for symbol, symbol_alerts in by_symbol.items():
                # Normalize the symbol to ccxt format (BTCUSDT → BTC/USDT).
                ccxt_symbol = _normalize_ccxt_symbol(symbol)

                try:
                    candles = await _asyncio.to_thread(
                        public_exchange.fetch_ohlcv,
                        symbol=ccxt_symbol,
                        timeframe="1h",
                        limit=100,
                    )
                except Exception as exc:
                    logger.warning(
                        "Advanced alert check: failed to fetch candles for %s: %s",
                        symbol, exc,
                    )
                    continue

                if not candles or len(candles) < 20:
                    continue

                # Convert to dict format expected by the detectors.
                candle_dicts = [
                    {
                        "time": c[0],
                        "open": c[1],
                        "high": c[2],
                        "low": c[3],
                        "close": c[4],
                        "volume": c[5],
                    }
                    for c in candles
                ]

                signals = detect_all_signals(symbol, candle_dicts)

                if not signals:
                    continue

                # Only match detector events to alert types configured for this symbol.
                signal_by_type = select_advanced_signals(
                    signals, {str(alert.alert_type) for alert in symbol_alerts}
                )

                for alert in symbol_alerts:
                    if alert.alert_type not in signal_by_type:
                        continue
                    if _is_advanced_alert_in_cooldown(alert):
                        continue

                    matching_signals = signal_by_type[alert.alert_type]
                    for sig in matching_signals:
                        await _trigger_advanced_alert(
                            session, alert, sig, candle_dicts[-1]["close"],
                        )

        except Exception as exc:
            logger.exception("Advanced alert check failed: %s", exc)


def _normalize_ccxt_symbol(symbol: str) -> str:
    """Normalize a dashboard symbol to ccxt format.

    Accepts: BTCUSDT, BTC-USDT, BTC/USDT, BTC-USD
    Returns: BTC/USDT
    """
    s = symbol.upper().strip()
    # Already ccxt format.
    if "/" in s:
        return s
    # Strip common suffixes.
    if s.endswith("USDT"):
        base = s[:-4]
        return f"{base}/USDT"
    if s.endswith("USD"):
        base = s[:-3]
        return f"{base}/USDT"
    # Fallback: try with the symbol as-is.
    return s


def _is_advanced_alert_in_cooldown(alert: PriceAlert) -> bool:
    """Return True if the advanced alert was triggered within the cooldown."""
    if alert.triggered_at is None:
        return False
    try:
        from datetime import timedelta

        last = alert.triggered_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last < timedelta(hours=COOLDOWN_HOURS)
    except Exception:
        return False


async def _trigger_advanced_alert(
    session: AsyncSession,
    alert: PriceAlert,
    signal: dict[str, Any],
    current_price: float,
) -> None:
    """Mark an advanced alert as triggered and send notifications."""
    from backend.services.price_alert_service import _trigger_alert

    # Reuse the existing trigger handler which sends to all enabled channels.
    await _trigger_alert(session, alert, current_price)
    logger.info(
        "Advanced alert triggered: id=%d type=%s symbol=%s — %s",
        alert.id, alert.alert_type, alert.symbol, signal.get("message", ""),
    )


# ── Position alert check job (cross-reference positions with Miraj scan) ──


# In-memory dedup store: {(user_id, symbol, alert_type): last_sent_ts}
_position_alert_dedup: dict[tuple[int, str, str], float] = {}
_POSITION_ALERT_DEDUP_SECONDS = 3600  # 1 hour


async def check_position_alerts_job() -> None:
    """APScheduler job callback — check open positions against the Miraj scan.

    For every connected ``(user_id, exchange)`` pair:
      1. Loads the cached open positions.
      2. Runs the position-alert service (which fetches/caches scans).
      3. For any DANGER alert, sends a Telegram notification (1-hour dedup).

    Runs every 10 minutes.
    """
    logger.info("Position alert check: starting")

    from backend.routes.portfolio import _load_positions, _serialise_position
    from backend.services.position_alert_service import compute_position_alerts
    from backend.services.exchange_service import is_ccxt_available

    if not is_ccxt_available():
        logger.info("Position alert check: ccxt not installed — skipping")
        return

    factory = get_session_factory()
    async with factory() as session:
        try:
            # Find every connected (user, exchange) pair
            result = await session.execute(select(ExchangeKey))
            key_rows = result.scalars().all()

            if not key_rows:
                logger.info("Position alert check: no connected users — skipping")
                return

            import time as _time

            now_ts = _time.time()
            sent_count = 0

            for row in key_rows:
                user_id = row.user_id
                exchange_slug = row.exchange

                try:
                    positions = await _load_positions(
                        session, user_id, exchange_slug,
                    )
                    if not positions:
                        continue

                    position_dicts = [_serialise_position(p) for p in positions]
                    alert_items = await compute_position_alerts(position_dicts)

                    if not alert_items:
                        continue

                    # ── Collect DANGER alerts for Telegram ───────────
                    danger_alerts = [
                        item for item in alert_items
                        if item.get("max_severity") == "DANGER"
                    ]
                    if not danger_alerts:
                        continue

                    # Fetch the user's Telegram chat id
                    from backend.models import AlertChannel

                    channel_result = await session.execute(
                        select(AlertChannel).where(
                            AlertChannel.user_id == user_id,
                            AlertChannel.channel_type == "telegram",
                            AlertChannel.enabled == 1,
                        )
                    )
                    telegram_channel = channel_result.scalar_one_or_none()
                    if telegram_channel is None:
                        logger.debug(
                            "Position alert: user %d has no Telegram channel — skipping",
                            user_id,
                        )
                        continue

                    # Parse chat_id from config JSON
                    import json as _json

                    chat_id: Optional[str] = None
                    try:
                        config = _json.loads(telegram_channel.config or "{}")
                        chat_id = str(config.get("chat_id", "")).strip() or None
                    except (ValueError, TypeError):
                        chat_id = None

                    if not chat_id:
                        logger.debug(
                            "Position alert: user %d Telegram channel has no chat_id",
                            user_id,
                        )
                        continue

                    # ── Send each DANGER alert (dedup'd per hour) ────
                    from backend.alerts.telegram import send_alert

                    for item in danger_alerts:
                        symbol = item.get("symbol", "?")
                        for alert in item.get("alerts", []):
                            if alert.get("severity") != "DANGER":
                                continue
                            alert_type = alert.get("type", "UNKNOWN")
                            dedup_key = (user_id, symbol, alert_type)
                            last_sent = _position_alert_dedup.get(dedup_key)
                            if (
                                last_sent is not None
                                and (now_ts - last_sent)
                                < _POSITION_ALERT_DEDUP_SECONDS
                            ):
                                continue  # dedup: skip within 1 hour

                            message = (
                                f"\U0001f6a8 *DANGER* — Position Alert\n"
                                f"\U0001f3f7 *{symbol}* ({item.get('position_side', '')})\n"
                                f"\U0001f4cc {alert.get('message', '')}\n"
                                f"\U0001f4a1 Action: {alert.get('action', 'Review position')}"
                            )
                            sent = await send_alert(chat_id, message)
                            if sent:
                                sent_count += 1
                                _position_alert_dedup[dedup_key] = now_ts
                                logger.info(
                                    "Position alert: sent DANGER alert to user %d "
                                    "for %s (%s)",
                                    user_id, symbol, alert_type,
                                )

                except Exception as exc:
                    logger.warning(
                        "Position alert check: error for user %d / %s: %s",
                        user_id, exchange_slug, exc,
                    )
                    continue

            # ── Purge stale dedup entries (older than 2h) ──────────
            stale_cutoff = now_ts - (2 * _POSITION_ALERT_DEDUP_SECONDS)
            stale_keys = [
                k for k, ts in _position_alert_dedup.items()
                if ts < stale_cutoff
            ]
            for k in stale_keys:
                _position_alert_dedup.pop(k, None)

            logger.info(
                "Position alert check: complete — %d DANGER alerts sent",
                sent_count,
            )

        except Exception as exc:
            logger.exception("Position alert check failed: %s", exc)


# ── Lifecycle helpers ──────────────────────────────────────────────────────


def setup_scheduler(app) -> AsyncIOScheduler:
    """Configure the scheduler, attach the 4-hour scan, price alert checks, and daily digest jobs.

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
    scheduler.add_job(
        _check_price_alerts_job,
        trigger=CronTrigger(minute="*/2"),  # every 2 minutes
        id="check_price_alerts",
        name="Price alert check (every 2m)",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_all_portfolios_job,
        trigger=CronTrigger(minute="*/5"),  # every 5 minutes
        id="portfolio_auto_refresh",
        name="Portfolio auto-refresh (every 5m)",
        replace_existing=True,
    )
    scheduler.add_job(
        check_advanced_alerts_job,
        trigger=CronTrigger(minute="*/5"),  # every 5 minutes
        id="check_advanced_alerts",
        name="Advanced alerts — RSI/EMA/volume (every 5m)",
        replace_existing=True,
    )
    scheduler.add_job(
        check_position_alerts_job,
        trigger=CronTrigger(minute="*/10"),  # every 10 minutes
        id="check_position_alerts",
        name="Position alert check (every 10m)",
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
