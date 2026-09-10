"""Contract tests for signed collector public-report ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend.auth import create_access_token, hash_password
from backend.database import Base, get_engine, get_session_factory, set_db_path
from backend.models import CollectorIngestEvent, CollectorIngestFailure, CollectorIngestReplay, CollectorReport, User
from backend.schemas import CollectorReportIngestRequest

SENDER_SCRIPT_DIR = Path.home() / ".hermes" / "scripts"
sys.path.insert(0, str(SENDER_SCRIPT_DIR))
from solusdt_precompute import build_collector_report

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def app(tmp_path, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[FastAPI, None]:
    from backend import database

    monkeypatch.setenv("COLLECTOR_INGEST_SECRET", "collector-test-secret")
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(str(tmp_path / "collector_reports.db"))

    from backend.main import app as main_app

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield main_app
    await get_engine().dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client


async def _create_user_and_token() -> tuple[User, str]:
    factory = get_session_factory()
    async with factory() as session:
        user = User(username="collector-reader", email="collector-reader@example.com", hashed_password=hash_password("testpass123"))
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user, create_access_token(data={"sub": str(user.id)})


def _signed_headers(body: bytes, *, timestamp: int | None = None, nonce: str | None = None) -> dict[str, str]:
    timestamp = timestamp or int(time.time())
    nonce = nonce or str(uuid4())
    signature = hmac.new(b"collector-test-secret", f"{timestamp}.{nonce}.".encode("ascii") + body, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Collector-Timestamp": str(timestamp), "X-Collector-Nonce": nonce, "X-Collector-Signature": signature}


def _report_id(symbol: str, generated_at: str, payload_sha256: str) -> str:
    return f"{symbol.lower()}-{generated_at}-{payload_sha256[:32]}"


def _report(symbol: str = "SOLUSDT", *, generated_at: datetime | None = None) -> dict[str, object]:
    generated_at = generated_at or datetime.now(timezone.utc)
    generated_at_value = generated_at.isoformat()
    payload = {
        "generated_at": generated_at_value,
        "symbol": symbol,
        "venue": "mexc_spot",
        "source": "hourly_collector",
        "schema_version": "1.0",
        "verdict": {"state": "NO_TRADE", "summary": "No trade today.", "gates": [{"label": "HTF alignment", "state": "blocked", "reason": "Daily trend is mixed."}]},
        "quote": {"price": 142.35, "as_of": generated_at_value, "context_only": True},
        "scores": [{"label": "Trend", "value": 52, "maximum": 100}],
        "timeframes": [{"timeframe": "4h", "state": "mixed", "close": 142.35, "as_of": generated_at_value, "candles": []}],
        "source_health": [{"source": "mexc_spot_4h", "status": "ok", "checked_at": generated_at_value, "fallback": False}],
        "limitations": ["Public market data only."],
        "setup_states": _setup_states(),
    }
    payload_sha256 = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"report_id": _report_id(symbol, generated_at_value, payload_sha256), "payload_sha256": payload_sha256, **payload}


def _rebind_report_identity(payload: dict[str, object]) -> None:
    content = {key: value for key, value in payload.items() if key not in {"report_id", "payload_sha256"}}
    payload_sha256 = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    payload["payload_sha256"] = payload_sha256
    payload["report_id"] = _report_id(str(payload["symbol"]), str(payload["generated_at"]), payload_sha256)


def _normalized_report(payload: dict[str, object]) -> dict[str, object]:
    """Expected persisted shape: only validated, JSON-normalized allowlisted fields."""
    return CollectorReportIngestRequest.model_validate(payload).model_dump(
        mode="json", by_alias=True, exclude_unset=True, exclude_none=True,
    )


def _setup_states() -> list[dict[str, str]]:
    return [
        {"state": f"S{index}", "status": "passed" if index == 0 else "pending", "label": f"Setup {index}"}
        for index in range(6)
    ]


async def test_ingest_accepts_complete_ordered_public_setup_states(client: AsyncClient) -> None:
    payload = _report()
    payload["setup_states"] = _setup_states()
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 202
    assert response.json()["report"]["setup_states"] == _setup_states()


@pytest.mark.parametrize("setup_states", [None, [{"state": "S0", "status": "passed", "label": "Only one"}], list(reversed(_setup_states())), [{"state": f"S{index}", "status": "invalid", "label": "bad"} for index in range(6)]])
async def test_ingest_rejects_missing_or_malformed_setup_states(client: AsyncClient, setup_states: list[dict[str, str]] | None) -> None:
    payload = _report()
    if setup_states is None:
        del payload["setup_states"]
    else:
        payload["setup_states"] = setup_states
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid collector report"


async def test_signed_public_report_is_durable_and_latest_is_authenticated_and_symbol_scoped(client: AsyncClient) -> None:
    payload = _report()
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    ingested = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))
    assert ingested.status_code == 202
    assert ingested.json()["status"] == "validated"
    assert ingested.json()["report"] == _normalized_report(payload)

    assert (await client.get("/api/v1/collector-reports/latest?symbol=SOLUSDT")).status_code == 401
    _user, token = await _create_user_and_token()
    latest = await client.get("/api/v1/collector-reports/latest?symbol=SOLUSDT", headers={"Authorization": f"Bearer {token}"})

    assert latest.status_code == 200
    assert latest.json()["status"] == "validated"
    assert latest.json()["stale"] is False
    assert latest.json()["report"] == _normalized_report(payload)
    assert latest.json()["received_at"] is not None
    factory = get_session_factory()
    async with factory() as session:
        persisted = await session.get(CollectorReport, 1)
        assert persisted is not None
        assert persisted.status == "validated"
        assert persisted.validation_error is None
        events = (await session.scalars(select(CollectorIngestEvent).order_by(CollectorIngestEvent.id))).all()
        assert [(event.status, event.validation_error) for event in events] == [("received", None), ("validated", None)]
        assert all(event.request_digest == hashlib.sha256(body).hexdigest() for event in events)


async def test_actual_sender_signed_post_latest_response_passes_frontend_parser(client: AsyncClient, tmp_path: Path) -> None:
    report = build_collector_report({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot": {"lastPrice": "142.35"},
        "sources": {"mexc_spot_4h": "ok"},
        "timeframes": {
            "4h": {
                "summary": {"close": 142.35, "close_time_utc": "2026-09-10T04:00:00+00:00"},
                "last_rows": [{"open": "2026-09-10T00:00:00+00:00", "close": "2026-09-10T04:00:00+00:00", "o": 141, "h": 143, "l": 140, "c": 142.35, "v_sol": 3200}],
            },
        },
    })
    body = json.dumps(report, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    ingested = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))
    assert ingested.status_code == 202
    _user, token = await _create_user_and_token()
    latest = await client.get("/api/v1/collector-reports/latest?symbol=SOLUSDT", headers={"Authorization": f"Bearer {token}"})
    assert latest.status_code == 200
    response_path = tmp_path / "actual-sender-latest.json"
    response_path.write_text(json.dumps(latest.json()), encoding="utf-8")

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    result = subprocess.run(
        ["npm", "test", "--", "--runInBand", "lib/collector-reports-e2e.test.ts"],
        cwd=frontend_dir,
        env={**os.environ, "COLLECTOR_E2E_RESPONSE_PATH": str(response_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_authenticated_malformed_body_has_a_safe_received_to_failed_lifecycle(client: AsyncClient) -> None:
    body = b"{not-json"
    nonce = str(uuid4())
    headers = _signed_headers(body, nonce=nonce)
    rejected = await client.post("/api/v1/collector-reports", content=body, headers=headers)
    replay = await client.post("/api/v1/collector-reports", content=body, headers=headers)

    assert rejected.status_code == 422
    assert replay.status_code == 409
    assert replay.json()["detail"] == "Collector request replayed"
    factory = get_session_factory()
    async with factory() as session:
        events = (await session.scalars(select(CollectorIngestEvent).order_by(CollectorIngestEvent.id))).all()
        assert [(event.status, event.validation_error) for event in events] == [
            ("received", None),
            ("failed", "semantic_payload_invalid"),
        ]
        failure = await session.scalar(select(CollectorIngestFailure).where(CollectorIngestFailure.nonce == nonce))
        assert failure is not None
        assert failure.validation_error == "semantic_payload_invalid"
        assert (await session.scalar(select(CollectorIngestReplay).where(CollectorIngestReplay.nonce == nonce))) is not None
        assert (await session.scalar(select(CollectorReport))) is None
    assert b"{not-json" not in str([(event.request_digest, event.validation_error) for event in events]).encode()


async def test_ingest_rejects_declared_content_digest_mismatch(client: AsyncClient) -> None:
    payload = _report()
    payload["payload_sha256"] = "0" * 64
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 422
    assert response.json()["detail"] == "Collector payload digest mismatch"


async def test_ingest_rejects_report_id_not_bound_to_symbol_timestamp_and_digest(client: AsyncClient) -> None:
    payload = _report()
    payload["report_id"] = "arbitrary-report-id"
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 422
    assert response.json()["detail"] == "Collector report ID does not match content"


@pytest.mark.parametrize("forbidden_key", [
    "api_key", "private key", "auth_headers", "account_balances", "positions", "executable_order", "private_metadata", "execution_instructions",
    "private", "private_data", "privateExecutionContext", "execution", "execution_plan", "execution_metadata",
    "PRIVATE-DATA", "private data", "executionPlan", "execution-metadata",
])
async def test_ingest_rejects_nested_private_or_executable_payload_fields(client: AsyncClient, forbidden_key: str) -> None:
    payload = _report()
    payload["verdict"] = {"state": "NO_TRADE", "audit": {"deeply": [{forbidden_key: "never-persist"}]}}
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid collector report"
    assert "never-persist" not in response.text


@pytest.mark.parametrize(("field_path", "secret"), [
    ("verdict.summary", "api_key=private-key-material"),
    ("limitations", "api_key=private-key-material"),
    ("verdict.summary", "API Key = private-key-material"),
    ("limitations", "private-key: private-key-material"),
    ("limitations", "Authorization : Bearer private-key-material"),
    ("verdict.summary", "password=private-key-material"),
    ("limitations", "passwd: private-key-material"),
])
async def test_ingest_rejects_secret_like_allowlisted_text_without_persisting_it(
    client: AsyncClient, field_path: str, secret: str,
) -> None:
    payload = _report(f"TEXT{field_path[:1].upper()}USDT")
    if field_path == "verdict.summary":
        payload["verdict"] = {"state": "NO_TRADE", "summary": secret, "gates": []}
    else:
        payload["limitations"] = [secret]
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 422
    assert secret not in response.text
    factory = get_session_factory()
    async with factory() as session:
        reports = (await session.scalars(select(CollectorReport))).all()
        failures = (await session.scalars(select(CollectorIngestFailure))).all()
        events = (await session.scalars(select(CollectorIngestEvent))).all()
        assert all(secret not in str(report.__dict__) for report in reports)
        assert all(secret not in str(failure.__dict__) for failure in failures)
        assert all(secret not in str(event.__dict__) for event in events)
    _user, token = await _create_user_and_token()
    latest = await client.get(
        f"/api/v1/collector-reports/latest?symbol={payload['symbol']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert latest.status_code == 200
    assert secret not in latest.text


async def test_ingest_allows_public_analysis_prose_that_mentions_tokens_without_assignment(client: AsyncClient) -> None:
    payload = _report("PROSEUSDT")
    summary = "Token momentum is mixed; authorization of a trade is not warranted."
    payload["verdict"] = {"state": "NO_TRADE", "summary": summary, "gates": []}
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 202
    assert response.json()["report"]["verdict"]["summary"] == summary


async def test_ingest_rejects_unallowlisted_innocuous_nested_secret_value_without_persisting_it(client: AsyncClient) -> None:
    payload = _report("STRICTUSDT")
    payload["verdict"] = {
        "state": "NO_TRADE",
        "summary": "No trade today.",
        "gates": [],
        "note": "collector credential: private-key-material",
    }
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 422
    assert "private-key-material" not in response.text
    factory = get_session_factory()
    async with factory() as session:
        report = await session.scalar(select(CollectorReport).where(CollectorReport.symbol == "STRICTUSDT"))
        assert report is not None
        assert report.status == "failed"
        assert report.report == {}
        failures = (await session.scalars(select(CollectorIngestFailure))).all()
        assert len(failures) == 1
        assert all("private-key-material" not in str(failure.__dict__) for failure in failures)
        events = (await session.scalars(select(CollectorIngestEvent).order_by(CollectorIngestEvent.id))).all()
        assert [(event.status, event.validation_error) for event in events] == [
            ("received", None),
            ("failed", "semantic_payload_invalid"),
        ]
        assert all("private-key-material" not in str(event.__dict__) for event in events)


async def test_signed_unicode_public_text_uses_sender_canonical_digest_and_ingests(client: AsyncClient) -> None:
    payload = _report()
    payload["verdict"] = {"state": "NO_TRADE", "summary": "Résumé — 市场", "gates": []}
    _rebind_report_identity(payload)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    response = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert response.status_code == 202
    assert response.json()["status"] == "validated"
    assert response.json()["report"]["verdict"]["summary"] == "Résumé — 市场"


async def test_semantic_rejection_creates_safe_durable_failed_event_and_latest_hides_it(client: AsyncClient) -> None:
    payload = _report("REJECTUSDT")
    payload["verdict"] = {"state": "NO_TRADE", "private_metadata": {"token": "never-persist"}}
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    rejected = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))

    assert rejected.status_code == 422
    assert "never-persist" not in rejected.text
    factory = get_session_factory()
    async with factory() as session:
        failure = await session.get(CollectorIngestFailure, 1)
        report = await session.scalar(select(CollectorReport).where(CollectorReport.symbol == "REJECTUSDT"))
        assert failure is not None
        assert failure.validation_error == "semantic_payload_invalid"
        assert "never-persist" not in failure.validation_error
        assert report is not None
        assert report.status == "failed"
        assert report.report == {}
        assert report.validation_error == "semantic_payload_invalid"
        events = (await session.scalars(select(CollectorIngestEvent).order_by(CollectorIngestEvent.id))).all()
        assert [(event.status, event.validation_error) for event in events] == [
            ("received", None),
            ("failed", "semantic_payload_invalid"),
        ]
        assert all("never-persist" not in str(event.validation_error) for event in events)
    _user, token = await _create_user_and_token()
    latest = await client.get("/api/v1/collector-reports/latest?symbol=REJECTUSDT", headers={"Authorization": f"Bearer {token}"})

    assert latest.status_code == 200
    assert latest.json()["status"] == "failed"
    assert latest.json()["report"] is None
    assert "never-persist" not in latest.text


async def test_semantic_rejection_with_distinct_signed_nonces_is_audited_without_duplicate_failed_shell(client: AsyncClient) -> None:
    payload = _report("REPEATREJECTUSDT")
    payload["verdict"] = {"state": "NO_TRADE", "private_metadata": {"token": "never-persist"}}
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    first_nonce = str(uuid4())
    second_nonce = str(uuid4())

    first = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body, nonce=first_nonce))
    second = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body, nonce=second_nonce))

    assert first.status_code == 422
    assert second.status_code == 422
    factory = get_session_factory()
    async with factory() as session:
        events = (await session.scalars(select(CollectorIngestEvent).order_by(CollectorIngestEvent.id))).all()
        failures = (await session.scalars(select(CollectorIngestFailure).order_by(CollectorIngestFailure.id))).all()
        replays = (await session.scalars(select(CollectorIngestReplay).order_by(CollectorIngestReplay.id))).all()
        reports = (await session.scalars(select(CollectorReport).where(CollectorReport.symbol == "REPEATREJECTUSDT"))).all()
        assert [(event.nonce, event.status, event.validation_error) for event in events] == [
            (first_nonce, "received", None),
            (first_nonce, "failed", "semantic_payload_invalid"),
            (second_nonce, "received", None),
            (second_nonce, "failed", "semantic_payload_invalid"),
        ]
        assert [(failure.nonce, failure.validation_error) for failure in failures] == [
            (first_nonce, "semantic_payload_invalid"),
            (second_nonce, "semantic_payload_invalid"),
        ]
        assert {replay.nonce for replay in replays} == {first_nonce, second_nonce}
        assert len(reports) == 1
        assert reports[0].report == {}
        assert reports[0].status == "failed"
        assert all("never-persist" not in str(record.__dict__) for record in [*events, *failures, *replays, *reports])


async def test_semantic_rejection_consumes_its_signed_nonce(client: AsyncClient) -> None:
    payload = _report("REPLAYUSDT")
    payload["verdict"] = {"state": "NO_TRADE", "execution_instructions": {"action": "never-persist"}}
    _rebind_report_identity(payload)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    nonce = str(uuid4())

    first = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body, nonce=nonce))
    replay = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body, nonce=nonce))

    assert first.status_code == 422
    assert replay.status_code == 409
    assert "never-persist" not in replay.text


async def test_ingest_rejects_invalid_or_expired_hmac_and_is_idempotent_without_accepting_nonce_replay(client: AsyncClient) -> None:
    payload = _report()
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    nonce = str(uuid4())
    first = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body, nonce=nonce))
    assert first.status_code == 202

    replay = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body, nonce=nonce))
    assert replay.status_code == 409
    assert replay.json()["detail"] == "Collector request replayed"

    retry = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))
    assert retry.status_code == 202
    assert retry.json()["idempotent"] is True

    invalid = await client.post("/api/v1/collector-reports", content=body, headers={**_signed_headers(body), "X-Collector-Signature": "0" * 64})
    assert invalid.status_code == 401
    expired = await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body, timestamp=int(time.time()) - 301))
    assert expired.status_code == 401


async def test_latest_reports_failed_state_without_exposing_validation_error(client: AsyncClient) -> None:
    factory = get_session_factory()
    now = datetime.now(timezone.utc)
    async with factory() as session:
        session.add(CollectorReport(
            report_id="failed-public-report",
            symbol="FAILUSDT",
            generated_at=now,
            report={"public": "safe"},
            payload_digest="f" * 64,
            status="failed",
            validation_error="api_key=must-not-leak",
        ))
        await session.commit()
    _user, token = await _create_user_and_token()

    response = await client.get("/api/v1/collector-reports/latest?symbol=FAILUSDT", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["stale"] is True
    assert body["received_at"] is not None
    assert body["report"] is None
    assert "must-not-leak" not in response.text


async def test_latest_returns_stale_or_unavailable_without_inventing_a_report(client: AsyncClient) -> None:
    _user, token = await _create_user_and_token()
    headers = {"Authorization": f"Bearer {token}"}
    unavailable = await client.get("/api/v1/collector-reports/latest?symbol=BTCUSDT", headers=headers)
    assert unavailable.status_code == 200
    assert unavailable.json() == {"status": "unavailable", "stale": True, "received_at": None, "report": None}

    payload = _report("BTCUSDT", generated_at=datetime.now(timezone.utc) - timedelta(minutes=16))
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    assert (await client.post("/api/v1/collector-reports", content=body, headers=_signed_headers(body))).status_code == 202
    stale = await client.get("/api/v1/collector-reports/latest?symbol=BTCUSDT", headers=headers)
    assert stale.status_code == 200
    assert stale.json()["status"] == "stale"
    assert stale.json()["stale"] is True
    assert stale.json()["report"] == _normalized_report(payload)
