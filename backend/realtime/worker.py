"""Dedicated advisory MEXC monitoring worker.

This process has no order-placement code.  It subscribes to public MEXC kline
streams, evaluates only closed candles, persists lifecycle transitions, and
notifies enabled user channels when an actionable/invalidation/stale transition
occurs.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import signal
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session_factory
from backend.models import AlertChannel, AlertHistory, RealtimeNotification, RealtimeSignal, WatchlistPair
from backend.realtime.lifecycle import Confirmation, SignalEvaluation, SignalLifecycle, SignalState
from backend.realtime.mexc_stream import (
    MEXC_CONTRACT_WS_URL,
    KlineCandle,
    build_kline_subscription,
    parse_kline_message,
    parse_rest_klines,
    to_mexc_symbol,
)
from backend.realtime.store import enqueue_transition_notifications, record_transition

logger = logging.getLogger(__name__)
AlertSender = Callable[[int, Confirmation, SignalEvaluation], Awaitable[None]]


class MonitoringCoordinator:
    """Persists every state and sends only meaningful changed transitions."""

    def __init__(self, alert_sender: AlertSender | None = None) -> None:
        self._lifecycle = SignalLifecycle()
        self._alert_sender = alert_sender

    async def process(self, session: AsyncSession, user_id: int, confirmation: Confirmation) -> SignalEvaluation:
        evaluation = self._lifecycle.evaluate(confirmation)
        stored = await record_transition(
            session, user_id, confirmation.symbol, confirmation.direction, evaluation
        )
        if stored.changed and evaluation.state in {SignalState.ACTIONABLE, SignalState.INVALIDATED, SignalState.STALE}:
            await enqueue_transition_notifications(session, stored.signal, evaluation)
        return evaluation


async def send_realtime_alert(
    session: AsyncSession,
    user_id: int,
    confirmation: Confirmation,
    evaluation: SignalEvaluation,
) -> None:
    """Deliver one lifecycle message through the user's enabled channels."""
    channels = (
        await session.execute(
            select(AlertChannel).where(
                AlertChannel.user_id == user_id,
                AlertChannel.enabled == 1,
            )
        )
    ).scalars().all()
    if not channels:
        logger.info("Real-time signal %s for user %s has no enabled channel", evaluation.dedup_key, user_id)
        return

    missing = ", ".join(evaluation.missing_gates) or "none"
    text = (
        f"*{evaluation.state.value}* — {confirmation.symbol} {confirmation.direction}\n"
        "Mode: advisory/manual execution only\n"
        f"Missing gates: {missing}\n"
        f"Signal: `{evaluation.dedup_key}`"
    )
    for channel in channels:
        try:
            config = json.loads(channel.config or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}
        sent = False
        if channel.channel_type == "telegram" and config.get("chat_id"):
            from backend.alerts.telegram import send_alert
            sent = await send_alert(str(config["chat_id"]), text)
        elif channel.channel_type == "discord" and config.get("webhook_url"):
            from backend.alerts.discord import send_webhook
            sent = await send_webhook(str(config["webhook_url"]), {"description": text})
        else:
            continue
        session.add(
            AlertHistory(
                user_id=user_id,
                pair=confirmation.symbol,
                channel=channel.channel_type,
                direction=confirmation.direction,
                message=text,
                status="sent" if sent else "failed",
            )
        )


async def dispatch_pending_notifications(session_factory: Any) -> None:
    """Deliver committed outbox rows; failures remain pending for a later retry."""
    async with session_factory() as session:
        pending = (
            await session.execute(
                select(RealtimeNotification).where(RealtimeNotification.status == "pending")
            )
        ).scalars().all()
        now = datetime.datetime.utcnow()
        for notification in pending:
            if notification.next_attempt_at and notification.next_attempt_at > now:
                continue
            signal_row = await session.get(RealtimeSignal, notification.signal_id)
            channel = await session.get(AlertChannel, notification.channel_id)
            notification.attempts += 1
            if signal_row is None or channel is None or not channel.enabled:
                notification.status = "cancelled"
                continue
            text = (
                f"*{signal_row.state}* — {signal_row.pair} {signal_row.direction}\n"
                "Mode: advisory/manual execution only\n"
                f"Signal: `{notification.dedup_key}`"
            )
            try:
                config = json.loads(channel.config or "{}")
                if channel.channel_type == "telegram" and config.get("chat_id"):
                    from backend.alerts.telegram import send_alert
                    sent = await send_alert(str(config["chat_id"]), text)
                elif channel.channel_type == "discord" and config.get("webhook_url"):
                    from backend.alerts.discord import send_webhook
                    sent = await send_webhook(str(config["webhook_url"]), {"description": text})
                else:
                    notification.status = "cancelled"
                    continue
            except Exception as exc:
                notification.last_error = str(exc)[:500]
                sent = False
            if sent:
                notification.status = "sent"
                notification.sent_at = now
                notification.next_attempt_at = None
                notification.last_error = None
            else:
                notification.next_attempt_at = now + datetime.timedelta(seconds=min(300, 2 ** min(notification.attempts, 8)))
        await session.commit()


@dataclass
class _Series:
    candles: deque[KlineCandle]


class CandleStrategy:
    """Conservative closed-candle adapter for the explicit confirmation gates."""

    def __init__(self) -> None:
        self._series: dict[tuple[str, str], _Series] = {}

    def add(self, interval: str, candle: KlineCandle) -> bool:
        key = (candle.symbol, interval)
        series = self._series.setdefault(key, _Series(deque(maxlen=80))).candles
        if series and series[-1].timestamp_ms == candle.timestamp_ms:
            series[-1] = candle
            return False
        series.append(candle)
        return len(series) > 1  # the preceding candle is now closed

    def confirmations(self, symbol: str, direction: str, data_fresh: bool) -> Confirmation | None:
        five = self._closed(symbol, "Min5", 22)
        fifteen = self._closed(symbol, "Min15", 22)
        hour = self._closed(symbol, "Min60", 22)
        four_hour = self._closed(symbol, "Hour4", 22)
        if not all((five, fifteen, hour, four_hour)):
            return None

        price = five[-1].close
        h_closes = [c.close for c in hour]
        fh_closes = [c.close for c in four_hour]
        long = direction == "LONG"
        higher = (h_closes[-1] > _mean(h_closes[-20:]) and fh_closes[-1] > _mean(fh_closes[-20:])) if long else (
            h_closes[-1] < _mean(h_closes[-20:]) and fh_closes[-1] < _mean(fh_closes[-20:])
        )

        swing_high, swing_low = max(c.high for c in hour[-20:]), min(c.low for c in hour[-20:])
        span = swing_high - swing_low
        if span <= 0:
            return None
        zone = (swing_high - span * 0.786, swing_high - span * 0.618) if long else (
            swing_low + span * 0.618, swing_low + span * 0.786
        )
        in_zone = zone[0] <= price <= zone[1]
        previous = five[-2]
        recent = five[-7:-1]
        retest = (five[-1].low <= min(c.low for c in recent) and five[-1].close > five[-1].open) if long else (
            five[-1].high >= max(c.high for c in recent) and five[-1].close < five[-1].open
        )
        five_confirm = five[-1].close > previous.high if long else five[-1].close < previous.low
        fifteen_momentum = fifteen[-1].close > _mean([c.close for c in fifteen[-15:]]) if long else (
            fifteen[-1].close < _mean([c.close for c in fifteen[-15:]])
        )
        volume = five[-1].volume > _mean([c.volume for c in five[-21:-1]])
        invalidated = price < swing_low if long else price > swing_high
        return Confirmation(
            symbol=symbol,
            direction=direction,
            higher_timeframe_aligned=higher,
            in_entry_zone=in_zone,
            retest_confirmed=retest,
            five_minute_confirmed=five_confirm,
            fifteen_minute_qqe_confirmed=fifteen_momentum,
            volume_confirmed=volume,
            invalidation_hit=invalidated,
            data_fresh=data_fresh,
        )

    def _closed(self, symbol: str, interval: str, minimum: int) -> list[KlineCandle] | None:
        items = list(self._series.get((symbol, interval), _Series(deque())).candles)
        # Omit the active exchange candle; decisions use completed bars only.
        closed = items[:-1]
        return closed if len(closed) >= minimum else None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


class MexcMonitoringWorker:
    """Reconnect-safe MEXC public-stream worker for all active watchlist pairs."""

    intervals = ("Min5", "Min15", "Min60", "Hour4")

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._strategy = CandleStrategy()
        self._last_frame_by_symbol: dict[str, float] = {}
        self._last_stale_check_at = 0.0
        self._heartbeat_path = os.environ.get("MONITOR_HEARTBEAT_FILE", "/tmp/mexc-monitor.heartbeat")
        self._users_by_symbol: dict[str, set[int]] = defaultdict(set)

    def _touch_heartbeat(self) -> None:
        with open(self._heartbeat_path, "w", encoding="utf-8") as heartbeat:
            heartbeat.write(str(time.time()))

    async def run(self) -> None:
        await self._load_watchlist()
        if not self._users_by_symbol:
            logger.warning("Real-time worker has no watchlist pairs; stopping")
            return
        needs_reconciliation = True
        while not self._stop.is_set():
            try:
                if needs_reconciliation:
                    await self._hydrate_history()
                    needs_reconciliation = False
                await self._stream_once()
            except Exception as exc:
                needs_reconciliation = True
                logger.exception("MEXC stream failed; reconciling before reconnect in 5 seconds: %s", exc)
                await self._wait_to_reconnect(5)

    async def _wait_to_reconnect(self, seconds: float) -> None:
        """Wait for a reconnect interval unless shutdown was requested."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def _supported_watchlist_symbol(symbol: str) -> str | None:
        """Return a normalized MEXC Contract symbol, or exclude unsupported watchlist entries."""
        normalized = symbol.strip().upper().replace("_", "").replace("-", "").replace("/", "")
        # The dashboard's generic spot-style watchlist stores BTC-USD; MEXC
        # Contract executes the corresponding USDT perpetual as BTC_USDT.
        if normalized.endswith("USD") and not normalized.endswith("USDT"):
            normalized = f"{normalized}T"
        try:
            to_mexc_symbol(normalized)
        except ValueError:
            return None
        return normalized

    async def _load_watchlist(self) -> None:
        async with get_session_factory()() as session:
            rows = (await session.execute(select(WatchlistPair))).scalars().all()
        for row in rows:
            symbol = self._supported_watchlist_symbol(row.pair)
            if symbol is None:
                logger.warning("Skipping unsupported non-MEXC-USDT watchlist pair: %s", row.pair)
                continue
            self._users_by_symbol[symbol].add(row.user_id)
        logger.info("Real-time worker loaded %d supported MEXC watchlist pairs", len(self._users_by_symbol))

    async def _hydrate_history(self) -> None:
        """Backfill enough public MEXC candles before evaluating live frames."""
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            for symbol in self._users_by_symbol:
                mexc_symbol = to_mexc_symbol(symbol)
                for interval in self.intervals:
                    response = await client.get(
                        f"https://contract.mexc.com/api/v1/contract/kline/{mexc_symbol}",
                        params={"interval": interval, "limit": 80},
                    )
                    response.raise_for_status()
                    for candle in parse_rest_klines(mexc_symbol, response.json()):
                        self._strategy.add(interval, candle)
        logger.info("MEXC candle backfill completed for %d symbols", len(self._users_by_symbol))
        self._touch_heartbeat()

    async def _stream_once(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets dependency is required for real-time monitoring") from exc
        async with websockets.connect(MEXC_CONTRACT_WS_URL, ping_interval=20, ping_timeout=20) as socket:
            for symbol in self._users_by_symbol:
                for interval in self.intervals:
                    await socket.send(json.dumps(build_kline_subscription(symbol, interval)))
            logger.info("Connected to MEXC market stream for %d symbols", len(self._users_by_symbol))
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=30)
                except asyncio.TimeoutError:
                    await socket.send(json.dumps({"method": "ping"}))
                    await self._check_stale_symbols()
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                candle = parse_kline_message(message)
                if candle is None:
                    continue
                self._last_frame_by_symbol[candle.symbol] = time.monotonic()
                self._touch_heartbeat()
                await self._check_stale_symbols()
                interval = str(message.get("interval") or message.get("data", {}).get("interval") or "")
                if interval not in self.intervals:
                    continue
                if self._strategy.add(interval, candle):
                    await self._evaluate_symbol(candle.symbol)

    def _is_symbol_fresh(self, symbol: str) -> bool:
        last_frame_at = self._last_frame_by_symbol.get(symbol)
        return last_frame_at is not None and time.monotonic() - last_frame_at <= 20

    async def _check_stale_symbols(self) -> None:
        """Persist one STALE transition per silent symbol; never evaluate it as actionable."""
        now = time.monotonic()
        if now - self._last_stale_check_at < 20:
            return
        self._last_stale_check_at = now
        stale_symbols = [symbol for symbol in self._users_by_symbol if not self._is_symbol_fresh(symbol)]
        if not stale_symbols:
            return
        async with get_session_factory()() as session:
            coordinator = MonitoringCoordinator(
                lambda user_id, c, e: send_realtime_alert(session, user_id, c, e)
            )
            for symbol in stale_symbols:
                for direction in ("LONG", "SHORT"):
                    confirmation = Confirmation(symbol, direction, False, False, False, False, False, False, data_fresh=False)
                    for user_id in self._users_by_symbol[symbol]:
                        await coordinator.process(session, user_id, confirmation)
            await session.commit()
        await dispatch_pending_notifications(get_session_factory())

    async def _evaluate_symbol(self, symbol: str) -> None:
        fresh = self._is_symbol_fresh(symbol)
        async with get_session_factory()() as session:
            coordinator = MonitoringCoordinator(
                lambda user_id, c, e: send_realtime_alert(session, user_id, c, e)
            )
            for direction in ("LONG", "SHORT"):
                confirmation = self._strategy.confirmations(symbol, direction, fresh)
                if confirmation is None:
                    continue
                for user_id in self._users_by_symbol.get(symbol, ()):
                    await coordinator.process(session, user_id, confirmation)
            await session.commit()
        await dispatch_pending_notifications(get_session_factory())


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    worker = MexcMonitoringWorker()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
    loop.run_until_complete(worker.run())


if __name__ == "__main__":
    main()
