"""Durability and retry coverage for the signed signal webhook outbox."""

from __future__ import annotations

import asyncio
import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete, func, select

from backend.alerts.webhook import WebhookDeliveryResult, build_signal_event
from backend.alerts.webhook_outbox import (
    _dispatch_one,
    build_webhook_config_fingerprint,
    cleanup_terminal_signal_webhooks,
    dispatch_pending_signal_webhooks,
    enqueue_signal_webhook,
)
from backend.alerts.manager import _count_recent_alerts
from backend.database import Base, get_engine, get_session_factory, set_db_path
from backend.models import AlertChannel, AlertHistory, SignalWebhookDelivery, User
from backend.scheduler import (
    cleanup_signal_webhooks_job,
    dispatch_signal_webhooks_job,
    setup_scheduler,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def outbox_db(tmp_path):
    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(str(tmp_path / "signal-webhook-outbox.db"))
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = get_session_factory()
    async with factory() as session:
        user = User(
            username="outbox-user",
            email="outbox@example.com",
            hashed_password="not-used",
        )
        session.add(user)
        await session.flush()
        channel = AlertChannel(
            user_id=user.id,
            channel_type="webhook",
            config=json.dumps(
                {
                    "webhook_url": "https://hooks.example.com/miraj",
                    "signing_secret": "s" * 32,
                }
            ),
            enabled=1,
        )
        session.add(channel)
        await session.commit()
        user_id = user.id
        channel_id = channel.id

    yield factory, user_id, channel_id
    await get_engine().dispose()


def _payload(score: float = 88.0):
    return build_signal_event(
        symbol="SOLUSDT",
        score=score,
        direction="LONG",
        sent_at=datetime.datetime(2026, 8, 9, 7, 30, tzinfo=datetime.timezone.utc),
    )


async def _enqueue(user_id: int, channel_id: int, score: float = 88.0):
    return await enqueue_signal_webhook(
        user_id=user_id,
        channel_id=channel_id,
        pair="SOLUSDT",
        direction="LONG",
        score=score,
        payload=_payload(score),
        webhook_url="https://hooks.example.com/miraj",
        signing_secret="s" * 32,
    )


async def test_enqueue_commits_one_idempotent_secret_free_row(outbox_db):
    factory, user_id, channel_id = outbox_db

    first = await _enqueue(user_id, channel_id)
    with patch("backend.alerts.webhook_outbox.MAX_PENDING_PER_USER", 1):
        duplicate = await _enqueue(user_id, channel_id)

    assert first is not None and first.created is True
    assert duplicate is not None and duplicate.created is False
    assert duplicate.delivery_id == first.delivery_id

    async with factory() as session:
        rows = (await session.execute(select(SignalWebhookDelivery))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "pending"
        assert rows[0].attempts == 0
        assert "signing_secret" not in rows[0].payload
        assert rows[0].config_fingerprint == build_webhook_config_fingerprint(
            "https://hooks.example.com/miraj",
            "s" * 32,
        )
        assert rows[0].config_fingerprint != "s" * 32


async def test_dispatch_marks_success_and_writes_alert_history(outbox_db):
    factory, user_id, channel_id = outbox_db
    queued = await _enqueue(user_id, channel_id)
    delivered = WebhookDeliveryResult(True, queued.delivery_id, status_code=204)

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(return_value=delivered),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 1

    sender.assert_awaited_once()
    assert sender.await_args.kwargs["delivery_id"] == queued.delivery_id
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        history = (await session.execute(select(AlertHistory))).scalar_one()
        assert row.status == "sent"
        assert row.attempts == 1
        assert row.sent_at is not None
        assert history.status == "sent"
        assert json.loads(history.message)["delivery_id"] == queued.delivery_id


async def test_retry_reuses_delivery_id_after_timeout(outbox_db):
    factory, user_id, channel_id = outbox_db
    queued = await _enqueue(user_id, channel_id)
    timeout = WebhookDeliveryResult(False, queued.delivery_id, error="timeout")
    delivered = WebhookDeliveryResult(True, queued.delivery_id, status_code=202)

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(side_effect=[timeout, delivered]),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 1
        async with factory() as session:
            row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
            assert row.status == "pending"
            assert row.attempts == 1
            row.next_attempt_at = datetime.datetime.utcnow() - datetime.timedelta(
                seconds=1
            )
            await session.commit()
        assert await dispatch_pending_signal_webhooks(factory) == 1

    assert [call.kwargs["delivery_id"] for call in sender.await_args_list] == [
        queued.delivery_id,
        queued.delivery_id,
    ]
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        histories = (await session.execute(select(AlertHistory))).scalars().all()
        assert row.status == "sent"
        assert row.attempts == 2
        assert [history.status for history in histories] == ["failed", "sent"]


async def test_expired_lease_is_reclaimed_with_same_delivery_id(outbox_db):
    factory, user_id, channel_id = outbox_db
    queued = await _enqueue(user_id, channel_id)
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        row.status = "processing"
        row.lease_expires_at = datetime.datetime.utcnow() - datetime.timedelta(
            seconds=1
        )
        await session.commit()

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(
            return_value=WebhookDeliveryResult(
                True,
                queued.delivery_id,
                status_code=200,
            )
        ),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 1

    assert sender.await_args.kwargs["delivery_id"] == queued.delivery_id


async def test_unexpected_sender_exception_becomes_retryable_failure(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(side_effect=RuntimeError("unexpected")),
    ):
        assert await dispatch_pending_signal_webhooks(factory) == 1

    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        history = (await session.execute(select(AlertHistory))).scalar_one()
        assert row.status == "pending"
        assert row.last_error == "transport_error"
        assert history.status == "failed"
        assert json.loads(history.message)["error"] == "transport_error"


async def test_disabled_channel_cancels_without_network(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    async with factory() as session:
        channel = await session.get(AlertChannel, channel_id)
        channel.enabled = 0
        await session.commit()

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 1

    sender.assert_not_awaited()
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        assert row.status == "cancelled"
        assert row.last_error == "channel_unavailable"


async def test_scheduler_job_dispatches_committed_outbox():
    with patch(
        "backend.alerts.webhook_outbox.dispatch_pending_signal_webhooks",
        AsyncMock(return_value=2),
    ) as dispatcher:
        await dispatch_signal_webhooks_job()

    dispatcher.assert_awaited_once()


async def test_scheduler_cleanup_job_removes_expired_terminal_rows():
    with patch(
        "backend.alerts.webhook_outbox.cleanup_terminal_signal_webhooks",
        AsyncMock(return_value=2),
    ) as cleanup:
        await cleanup_signal_webhooks_job()

    cleanup.assert_awaited_once()


async def test_scheduler_registers_bounded_dispatch_and_daily_cleanup():
    scheduler = MagicMock()
    with patch("backend.scheduler.get_scheduler", return_value=scheduler):
        assert setup_scheduler(MagicMock()) is scheduler

    jobs = {call.kwargs["id"]: call.kwargs for call in scheduler.add_job.call_args_list}
    assert jobs["dispatch_signal_webhooks"]["max_instances"] == 1
    assert jobs["dispatch_signal_webhooks"]["coalesce"] is True
    assert jobs["cleanup_signal_webhooks"]["max_instances"] == 1
    assert jobs["cleanup_signal_webhooks"]["coalesce"] is True


async def test_queue_saturation_rejects_new_signal(outbox_db):
    _, user_id, channel_id = outbox_db
    assert await _enqueue(user_id, channel_id, score=88.0) is not None

    with patch("backend.alerts.webhook_outbox.MAX_PENDING_PER_USER", 1):
        assert await _enqueue(user_id, channel_id, score=89.0) is None


async def test_terminal_duplicate_is_atomically_redriven(outbox_db):
    factory, user_id, channel_id = outbox_db
    first = await _enqueue(user_id, channel_id)
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        row.status = "failed"
        row.attempts = 8
        row.last_error = "http_error"
        await session.commit()

    redriven = await _enqueue(user_id, channel_id)

    assert redriven.delivery_id == first.delivery_id
    assert redriven.created is False
    assert redriven.status == "pending"
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        assert row.status == "pending"
        assert row.attempts == 0
        assert row.last_error is None


async def test_queue_limit_is_enforced_under_concurrent_enqueues(outbox_db):
    factory, user_id, channel_id = outbox_db
    with patch("backend.alerts.webhook_outbox.MAX_PENDING_PER_USER", 1):
        results = await asyncio.gather(
            _enqueue(user_id, channel_id, score=88.0),
            _enqueue(user_id, channel_id, score=89.0),
        )

    assert sum(result is not None for result in results) == 1
    async with factory() as session:
        assert (await session.scalar(select(func.count(SignalWebhookDelivery.id)))) == 1


async def test_future_retry_and_active_lease_are_not_claimed(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id, score=88.0)
    await _enqueue(user_id, channel_id, score=89.0)
    future = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(SignalWebhookDelivery).order_by(SignalWebhookDelivery.id)
                )
            )
            .scalars()
            .all()
        )
        rows[0].next_attempt_at = future
        rows[1].status = "processing"
        rows[1].lease_expires_at = future
        await session.commit()

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 0

    sender.assert_not_awaited()


async def test_processing_row_without_lease_is_recovered(outbox_db):
    factory, user_id, channel_id = outbox_db
    queued = await _enqueue(user_id, channel_id)
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        row.status = "processing"
        row.lease_expires_at = None
        await session.commit()

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(
            return_value=WebhookDeliveryResult(
                True,
                queued.delivery_id,
                status_code=200,
            )
        ),
    ):
        assert await dispatch_pending_signal_webhooks(factory) == 1


async def test_dispatch_batch_cap_processes_oldest_row_first(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id, score=88.0)
    await _enqueue(user_id, channel_id, score=89.0)

    async def succeed(**kwargs):
        return WebhookDeliveryResult(
            True,
            kwargs["delivery_id"],
            status_code=204,
        )

    with (
        patch("backend.alerts.webhook_outbox.DISPATCH_BATCH_SIZE", 1),
        patch(
            "backend.alerts.webhook_outbox.send_signal_webhook",
            AsyncMock(side_effect=succeed),
        ),
    ):
        assert await dispatch_pending_signal_webhooks(factory) == 1

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(SignalWebhookDelivery).order_by(SignalWebhookDelivery.id)
                )
            )
            .scalars()
            .all()
        )
        assert [row.status for row in rows] == ["sent", "pending"]


async def test_competing_worker_cannot_claim_active_delivery(outbox_db):
    factory, user_id, channel_id = outbox_db
    queued = await _enqueue(user_id, channel_id)
    async with factory() as session:
        row_id = (await session.execute(select(SignalWebhookDelivery.id))).scalar_one()

    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_sender(**kwargs):
        started.set()
        await release.wait()
        return WebhookDeliveryResult(
            True,
            kwargs["delivery_id"],
            status_code=200,
        )

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(side_effect=blocked_sender),
    ):
        first_worker = asyncio.create_task(dispatch_pending_signal_webhooks(factory))
        await started.wait()
        assert await _dispatch_one(factory, row_id) is False
        release.set()
        assert await first_worker == 1

    async with factory() as session:
        row = await session.get(SignalWebhookDelivery, row_id)
        assert row.status == "sent"
        assert row.delivery_id == queued.delivery_id


async def test_deleted_row_cannot_be_claimed(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    async with factory() as session:
        row_id = (await session.execute(select(SignalWebhookDelivery.id))).scalar_one()
        await session.execute(
            delete(SignalWebhookDelivery).where(SignalWebhookDelivery.id == row_id)
        )
        await session.commit()

    assert await _dispatch_one(factory, row_id) is False


async def test_wrong_channel_type_cancels_pending_delivery(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    async with factory() as session:
        channel = await session.get(AlertChannel, channel_id)
        channel.channel_type = "telegram"
        await session.commit()

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 1

    sender.assert_not_awaited()
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        assert row.status == "cancelled"


@pytest.mark.parametrize(
    ("stored_config", "stored_payload"),
    [
        ("not-json", None),
        ("[]", None),
        ("{}", None),
        (None, "not-json"),
        (None, "[]"),
    ],
)
async def test_malformed_persisted_config_or_payload_fails_permanently(
    outbox_db,
    stored_config,
    stored_payload,
):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    async with factory() as session:
        channel = await session.get(AlertChannel, channel_id)
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        if stored_config is not None:
            channel.config = stored_config
        if stored_payload is not None:
            row.payload = stored_payload
        await session.commit()

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 1

    sender.assert_not_awaited()
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        assert row.status == "failed"
        assert row.last_error == "invalid_config"


@pytest.mark.parametrize(
    ("status_code", "expected_status"),
    [
        (400, "failed"),
        (408, "pending"),
        (429, "pending"),
        (503, "pending"),
    ],
)
async def test_http_status_controls_terminal_or_retry_state(
    outbox_db,
    status_code,
    expected_status,
):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)

    async def reject(**kwargs):
        return WebhookDeliveryResult(
            False,
            kwargs["delivery_id"],
            status_code=status_code,
            error="http_error",
        )

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(side_effect=reject),
    ):
        assert await dispatch_pending_signal_webhooks(factory) == 1

    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        assert row.status == expected_status
        assert (row.next_attempt_at is not None) is (expected_status == "pending")


async def test_max_attempts_turns_transient_failure_terminal(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        row.attempts = 7
        await session.commit()

    async def reject(**kwargs):
        return WebhookDeliveryResult(
            False,
            kwargs["delivery_id"],
            status_code=503,
            error="http_error",
        )

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(side_effect=reject),
    ):
        assert await dispatch_pending_signal_webhooks(factory) == 1

    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        assert row.status == "failed"
        assert row.attempts == 8


async def test_channel_delete_cascades_pending_delivery(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    async with factory() as session:
        channel = await session.get(AlertChannel, channel_id)
        await session.delete(channel)
        await session.commit()

    async with factory() as session:
        assert await session.scalar(select(SignalWebhookDelivery.id)) is None


async def test_dispatch_cancels_delivery_after_channel_config_rotation(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    async with factory() as session:
        channel = await session.get(AlertChannel, channel_id)
        channel.config = json.dumps(
            {
                "webhook_url": "https://replacement.example.com/miraj",
                "signing_secret": "r" * 32,
            }
        )
        await session.commit()

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 1

    sender.assert_not_awaited()
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        assert row.status == "cancelled"
        assert row.last_error == "channel_config_changed"


async def test_dispatch_rejects_cross_user_channel_ownership(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    async with factory() as session:
        other_user = User(
            username="other-user",
            email="other@example.com",
            hashed_password="not-used",
        )
        session.add(other_user)
        await session.flush()
        other_channel = AlertChannel(
            user_id=other_user.id,
            channel_type="webhook",
            config=json.dumps(
                {
                    "webhook_url": "https://other.example.com/miraj",
                    "signing_secret": "o" * 32,
                }
            ),
            enabled=1,
        )
        session.add(other_channel)
        await session.flush()
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        row.channel_id = other_channel.id
        await session.commit()

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(),
    ) as sender:
        assert await dispatch_pending_signal_webhooks(factory) == 1

    sender.assert_not_awaited()
    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        assert row.status == "cancelled"
        assert row.last_error == "channel_owner_mismatch"


async def test_dispatch_batch_is_fair_across_users(outbox_db):
    factory, first_user_id, first_channel_id = outbox_db
    await _enqueue(first_user_id, first_channel_id, score=88.0)
    await _enqueue(first_user_id, first_channel_id, score=89.0)
    async with factory() as session:
        second_user = User(
            username="fair-user",
            email="fair@example.com",
            hashed_password="not-used",
        )
        session.add(second_user)
        await session.flush()
        second_channel = AlertChannel(
            user_id=second_user.id,
            channel_type="webhook",
            config=json.dumps(
                {
                    "webhook_url": "https://fair.example.com/miraj",
                    "signing_secret": "f" * 32,
                }
            ),
            enabled=1,
        )
        session.add(second_channel)
        await session.commit()
        second_user_id = second_user.id
        second_channel_id = second_channel.id

    await enqueue_signal_webhook(
        user_id=second_user_id,
        channel_id=second_channel_id,
        pair="BTCUSDT",
        direction="SHORT",
        score=90.0,
        payload=build_signal_event(
            symbol="BTCUSDT",
            score=90.0,
            direction="SHORT",
            sent_at=datetime.datetime(2026, 8, 9, 7, 30, tzinfo=datetime.timezone.utc),
        ),
        webhook_url="https://fair.example.com/miraj",
        signing_secret="f" * 32,
    )

    async def succeed(**kwargs):
        return WebhookDeliveryResult(True, kwargs["delivery_id"], status_code=204)

    with (
        patch("backend.alerts.webhook_outbox.DISPATCH_BATCH_SIZE", 2),
        patch(
            "backend.alerts.webhook_outbox.send_signal_webhook",
            AsyncMock(side_effect=succeed),
        ),
    ):
        assert await dispatch_pending_signal_webhooks(factory) == 2

    async with factory() as session:
        sent_users = set(
            (
                await session.execute(
                    select(SignalWebhookDelivery.user_id).where(
                        SignalWebhookDelivery.status == "sent"
                    )
                )
            ).scalars()
        )
        assert sent_users == {first_user_id, second_user_id}


async def test_stale_worker_cannot_finalize_newer_lease(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_sender(**kwargs):
        started.set()
        await release.wait()
        return WebhookDeliveryResult(True, kwargs["delivery_id"], status_code=200)

    with patch(
        "backend.alerts.webhook_outbox.send_signal_webhook",
        AsyncMock(side_effect=blocked_sender),
    ):
        worker = asyncio.create_task(dispatch_pending_signal_webhooks(factory))
        await started.wait()
        async with factory() as session:
            row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
            replacement_lease = datetime.datetime.utcnow() + datetime.timedelta(
                minutes=5
            )
            row.lease_expires_at = replacement_lease
            await session.commit()
        release.set()
        assert await worker == 1

    async with factory() as session:
        row = (await session.execute(select(SignalWebhookDelivery))).scalar_one()
        histories = (await session.execute(select(AlertHistory))).scalars().all()
        assert row.status == "processing"
        assert row.lease_expires_at == replacement_lease
        assert histories == []


async def test_cooldown_counts_active_outbox_delivery(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id)

    async with factory() as session:
        count = await _count_recent_alerts(
            session,
            user_id,
            "SOLUSDT",
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4),
        )

    assert count == 1


async def test_retention_removes_only_expired_terminal_payloads(outbox_db):
    factory, user_id, channel_id = outbox_db
    await _enqueue(user_id, channel_id, score=88.0)
    await _enqueue(user_id, channel_id, score=89.0)
    old = datetime.datetime.utcnow() - datetime.timedelta(days=31)
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(SignalWebhookDelivery).order_by(SignalWebhookDelivery.id)
                )
            )
            .scalars()
            .all()
        )
        rows[0].status = "sent"
        rows[0].created_at = old
        rows[1].status = "pending"
        rows[1].created_at = old
        await session.commit()

    assert await cleanup_terminal_signal_webhooks(factory) == 1
    async with factory() as session:
        remaining = (
            (await session.execute(select(SignalWebhookDelivery))).scalars().all()
        )
        assert len(remaining) == 1
        assert remaining[0].status == "pending"
