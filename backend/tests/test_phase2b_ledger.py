"""Phase 2B capital-flow ledger coerce + persist tests."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import func, select

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import CapitalFlowLedger, ExchangeSyncState, User
from backend.tests.fixtures.phase2b_ledger import (
    DEPOSIT,
    DEPOSIT_IDLESS,
    FUNDING_IDLESS,
    FUNDING_RECEIPT,
    FUNDING_WITH_ID,
    TRANSFER_IN,
    TRANSFER_OUT,
    WITHDRAWAL,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="phase2b_ledger_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def session(tmp_db_path: str):
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(tmp_db_path)
    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = database.get_session_factory()
    async with factory() as s:
        yield s


async def _user(session, username: str = "phase2bledger") -> User:
    user = User(
        username=username,
        email=f"{username}@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def test_signed_amount_conventions():
    from backend.services.phase2b_ledger import (
        coerce_deposit_row,
        coerce_funding_row,
        coerce_futures_transfer_row,
        coerce_withdrawal_row,
    )

    assert coerce_funding_row(FUNDING_WITH_ID)["signed_amount"] == -1.25
    assert coerce_funding_row(FUNDING_RECEIPT)["signed_amount"] == 0.55
    assert coerce_futures_transfer_row(TRANSFER_IN)["signed_amount"] == 50.0
    assert coerce_futures_transfer_row(TRANSFER_OUT)["signed_amount"] == -20.0
    assert coerce_deposit_row(DEPOSIT)["signed_amount"] == 100.0
    assert coerce_withdrawal_row(WITHDRAWAL)["signed_amount"] == -25.0


def test_idless_rows_get_stable_synthetic_exchange_entry_id():
    from backend.services.phase2b_ledger import coerce_funding_row, synthetic_exchange_entry_id

    a = coerce_funding_row(FUNDING_IDLESS)
    b = coerce_funding_row(dict(FUNDING_IDLESS))
    assert a["exchange_entry_id"]
    assert a["exchange_entry_id"] == b["exchange_entry_id"]
    assert a["exchange_entry_id"].startswith("synth:")
    # deterministic for same inputs
    assert a["exchange_entry_id"] == synthetic_exchange_entry_id(
        a["entry_type"], a["asset"], a["amount"], a["occurred_at"]
    )


async def test_persist_is_idempotent_on_double_ingest(session):
    from backend.services.phase2b_ledger import persist_capital_flow_payload

    user = await _user(session)
    now = datetime(2026, 8, 4, 12, 0, 0)
    payload = {
        "funding": [FUNDING_WITH_ID, FUNDING_IDLESS],
        "futures_transfers": [TRANSFER_IN, TRANSFER_OUT],
        "deposits": [DEPOSIT, DEPOSIT_IDLESS],
        "withdrawals": [WITHDRAWAL],
        "sync": {
            "funding": {"status": "fresh", "complete": True, "rows_fetched_total": 2, "source_total": 2},
            "futures_transfers": {"status": "fresh", "complete": True, "rows_fetched_total": 2, "source_total": 2},
            "deposits": {
                "status": "partial",
                "complete": False,
                "reason": "exchange_boundary_before_source_total",
                "rows_fetched_total": 2,
                "source_total": 10,
                "unrecoverable_gaps": [{"stream": "deposits", "reason": "exchange_boundary_before_source_total"}],
            },
            "withdrawals": {"status": "fresh", "complete": True, "rows_fetched_total": 1, "source_total": 1},
        },
    }
    await persist_capital_flow_payload(session, user.id, "mexc", payload, now)
    await session.commit()
    await persist_capital_flow_payload(session, user.id, "mexc", payload, now)
    await session.commit()

    count = await session.scalar(select(func.count()).select_from(CapitalFlowLedger))
    assert count == 7

    funding_state = await session.scalar(
        select(ExchangeSyncState).where(ExchangeSyncState.stream == "funding")
    )
    deposits_state = await session.scalar(
        select(ExchangeSyncState).where(ExchangeSyncState.stream == "deposits")
    )
    assert funding_state.status == "fresh"
    assert funding_state.complete is True
    assert deposits_state.status == "partial"
    assert deposits_state.complete is False
    assert deposits_state.partial_reason == "exchange_boundary_before_source_total"


async def test_unavailable_and_error_coverage_states_persist(session):
    from backend.services.phase2b_ledger import persist_capital_flow_payload

    user = await _user(session, "phase2bcov")
    now = datetime(2026, 8, 4, 13, 0, 0)
    await persist_capital_flow_payload(
        session,
        user.id,
        "mexc",
        {
            "funding": [],
            "futures_transfers": [],
            "deposits": [],
            "withdrawals": [],
            "sync": {
                "funding": {
                    "status": "unavailable",
                    "complete": False,
                    "reason": "stream_not_supported",
                    "rows_fetched_total": 0,
                },
                "futures_transfers": {
                    "status": "error",
                    "complete": False,
                    "error_code": "510",
                    "error_message": "rate limited for REDACTED synthetic-key value",
                    "rows_fetched_total": 0,
                },
                "deposits": {
                    "status": "unavailable",
                    "complete": False,
                    "reason": "stream_not_supported",
                    "rows_fetched_total": 0,
                },
                "withdrawals": {
                    "status": "unavailable",
                    "complete": False,
                    "reason": "stream_not_supported",
                    "rows_fetched_total": 0,
                },
            },
        },
        now,
    )
    await session.commit()
    states = {
        row.stream: row
        for row in (
            await session.scalars(select(ExchangeSyncState).where(ExchangeSyncState.user_id == user.id))
        ).all()
    }
    assert states["funding"].status == "unavailable"
    assert states["futures_transfers"].status == "error"
    assert "synthetic-key" not in (states["futures_transfers"].error_message_redacted or "")
