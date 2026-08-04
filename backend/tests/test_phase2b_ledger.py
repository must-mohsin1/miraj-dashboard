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
    # deterministic for same inputs (symbol + positionType disambiguate concurrent settlements)
    assert a["exchange_entry_id"] == synthetic_exchange_entry_id(
        a["entry_type"],
        a["asset"],
        a["amount"],
        a["occurred_at"],
        symbol=str(FUNDING_IDLESS.get("symbol") or ""),
        extra=str(FUNDING_IDLESS.get("positionType") or ""),
    )


def test_idless_funding_synth_id_differs_by_symbol():
    from backend.services.phase2b_ledger import coerce_funding_row
    from backend.tests.fixtures.phase2b_ledger import funding_row

    btc = coerce_funding_row(funding_row(None, funding="-0.10", offset=1))
    eth = coerce_funding_row({**funding_row(None, funding="-0.10", offset=1), "symbol": "ETH_USDT"})
    assert btc["exchange_entry_id"] != eth["exchange_entry_id"]


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


class MockMexcCapitalExchange:
    id = "mexc"
    markets = {}

    def __init__(self, **streams):
        self._streams = streams
        self.funding_pages_requested = []

    def contract_private_get_position_funding_records(self, params):
        self.funding_pages_requested.append(params.get("pageNum") or params.get("page_num") or 1)
        pages = self._streams.get("funding_pages", [[]])
        if isinstance(pages, dict):
            return pages
        page_num = int(params.get("pageNum") or params.get("page_num") or 1)
        page = pages[page_num - 1] if page_num <= len(pages) else []
        # MEXC real shape uses resultList + totalCount (not list/total).
        use_result_list = self._streams.get("funding_use_result_list", True)
        data = {
            "totalPage": max(len(pages), 1),
            "totalCount": sum(len(p) for p in pages),
            "currentPage": page_num,
            "pageSize": 100,
        }
        if use_result_list:
            data["resultList"] = page
        else:
            data["list"] = page
            data["total"] = data["totalCount"]
        return {"success": True, "data": data}

    def contract_private_get_account_transfer_record(self, params):
        pages = self._streams.get("transfer_pages", [[]])
        if isinstance(pages, dict):
            return pages
        page_num = int(params.get("pageNum") or params.get("page_num") or 1)
        page = pages[page_num - 1] if page_num <= len(pages) else []
        return {
            "success": True,
            "data": {
                "resultList": page,
                "totalPage": max(len(pages), 1),
                "totalCount": sum(len(p) for p in pages),
                "currentPage": page_num,
            },
        }

    def fetch_deposits(self, code=None, since=None, limit=None, params=None):
        return self._streams.get("deposits", [])

    def fetch_withdrawals(self, code=None, since=None, limit=None, params=None):
        return self._streams.get("withdrawals", [])


async def test_fetch_history_includes_capital_flow_streams_and_coverage():
    from backend.services.exchange_service import fetch_history

    exchange = MockMexcCapitalExchange(
        funding_pages=[[FUNDING_WITH_ID, FUNDING_RECEIPT]],
        transfer_pages=[[TRANSFER_IN]],
        deposits=[DEPOSIT],
        withdrawals=[WITHDRAWAL],
    )
    # attach position/order methods as empty so Phase 2A streams stay available
    exchange.contract_private_get_position_list_history_positions = lambda params: {
        "success": True, "data": {"list": [], "totalPage": 1, "total": 0}
    }
    exchange.contract_private_get_order_list_history_orders = lambda params: {
        "success": True, "data": {"list": [], "totalPage": 1, "total": 0}
    }

    data = await fetch_history(exchange, user_id=9)
    assert "funding" in data["sync"]
    assert data["sync"]["funding"]["status"] == "fresh"
    assert len(data["funding"]) == 2
    assert data["funding"][0]["entry_type"] == "funding"
    assert data["sync"]["deposits"]["rows_fetched_total"] == 1
    assert data["sync"]["withdrawals"]["complete"] is True


async def test_missing_capability_marks_stream_unavailable():
    from backend.services.exchange_service import fetch_history

    class Bare:
        id = "mexc"
        def contract_private_get_position_list_history_positions(self, params):
            return {"success": True, "data": {"list": [], "totalPage": 1, "total": 0}}
        def contract_private_get_order_list_history_orders(self, params):
            return {"success": True, "data": {"list": [], "totalPage": 1, "total": 0}}

    data = await fetch_history(Bare(), user_id=9)
    assert data["sync"]["funding"]["status"] == "unavailable"
    assert data["sync"]["funding"]["reason"] == "stream_not_supported"
    assert data["sync"]["futures_transfers"]["status"] == "unavailable"
    assert data["sync"]["deposits"]["status"] == "unavailable"
    assert data["sync"]["withdrawals"]["status"] == "unavailable"


async def test_funding_resultlist_shape_is_not_false_partial():
    """Regression: MEXC funding uses data.resultList + totalCount.

    Before the fix, only data.list/result were read → 0 rows + source_total=N →
    partial exchange_boundary (prod: funding 0 of 80, transfers 0 of 4).
    """
    from backend.services.exchange_service import fetch_history
    from backend.tests.fixtures.phase2b_ledger import FUNDING_RECEIPT, FUNDING_WITH_ID, TRANSFER_IN

    exchange = MockMexcCapitalExchange(
        funding_pages=[[FUNDING_WITH_ID, FUNDING_RECEIPT]],
        transfer_pages=[[TRANSFER_IN]],
        funding_use_result_list=True,
        deposits=[],
        withdrawals=[],
    )
    exchange.contract_private_get_position_list_history_positions = lambda params: {
        "success": True, "data": {"list": [], "totalPage": 1, "total": 0}
    }
    exchange.contract_private_get_order_list_history_orders = lambda params: {
        "success": True, "data": {"list": [], "totalPage": 1, "total": 0}
    }

    data = await fetch_history(exchange, user_id=9)

    assert len(data["funding"]) == 2
    assert data["sync"]["funding"]["status"] == "fresh"
    assert data["sync"]["funding"]["complete"] is True
    assert data["sync"]["funding"]["rows_fetched_total"] == 2
    assert data["sync"]["funding"]["source_total"] == 2
    assert data["sync"]["funding"].get("reason") is None

    assert len(data["futures_transfers"]) == 1
    assert data["sync"]["futures_transfers"]["status"] == "fresh"
    assert data["sync"]["futures_transfers"]["complete"] is True


def test_mexc_history_page_params_include_snake_and_camel():
    """Funding docs use page_num/page_size; positions often use pageNum/pageSize."""
    from backend.services.exchange_service import _mexc_history_page_params

    params = _mexc_history_page_params(3, 20)
    assert params["pageNum"] == 3
    assert params["page_num"] == 3
    assert params["pageSize"] == 20
    assert params["page_size"] == 20


class SnakeOnlyFundingExchange:
    """Mirrors prod: only snake_case page_num advances; camelCase is ignored."""

    id = "mexc"
    markets = {}

    def __init__(self, pages: list[list[dict]]):
        self.pages = pages
        self.requests: list[dict] = []

    def contract_private_get_position_funding_records(self, params):
        self.requests.append(dict(params))
        # Only honor snake_case — camelCase pageNum alone would stick on page 1.
        page_num = int(params.get("page_num") or 1)
        page = self.pages[page_num - 1] if 1 <= page_num <= len(self.pages) else []
        return {
            "success": True,
            "data": {
                "pageSize": 20,
                "totalCount": sum(len(p) for p in self.pages),
                "totalPage": len(self.pages),
                "currentPage": page_num,
                "resultList": page,
            },
        }

    def contract_private_get_account_transfer_record(self, params):
        return {
            "success": True,
            "data": {"resultList": [], "totalPage": 1, "totalCount": 0, "currentPage": 1},
        }

    def fetch_deposits(self, code=None, since=None, limit=None, params=None):
        return []

    def fetch_withdrawals(self, code=None, since=None, limit=None, params=None):
        return []


def _attach_empty_position_order(exchange):
    exchange.contract_private_get_position_list_history_positions = lambda params: {
        "success": True, "data": {"list": [], "totalPage": 1, "total": 0}
    }
    exchange.contract_private_get_order_list_history_orders = lambda params: {
        "success": True, "data": {"list": [], "totalPage": 1, "total": 0}
    }
    return exchange


async def test_funding_pagination_uses_snake_case_and_keeps_all_unique_ids():
    """Regression: prod claimed 80 fresh funding rows but ledger held 20.

    Root cause: pageNum/pageSize ignored by funding endpoint → 4× same page of 20.
    Fix: send page_num/page_size (and camelCase), dedupe by id.
    """
    from backend.services.exchange_service import fetch_history
    from backend.tests.fixtures.phase2b_ledger import funding_row

    pages = [
        [funding_row(f"fund-p1-{i}", funding=f"-0.0{i}", offset=i) for i in range(20)],
        [funding_row(f"fund-p2-{i}", funding=f"-0.1{i}", offset=20 + i) for i in range(20)],
        [funding_row(f"fund-p3-{i}", funding=f"-0.2{i}", offset=40 + i) for i in range(20)],
        [funding_row(f"fund-p4-{i}", funding=f"-0.3{i}", offset=60 + i) for i in range(20)],
    ]
    exchange = _attach_empty_position_order(SnakeOnlyFundingExchange(pages))

    data = await fetch_history(exchange, user_id=9)

    assert len(data["funding"]) == 80
    assert data["sync"]["funding"]["rows_fetched_total"] == 80
    assert data["sync"]["funding"]["source_total"] == 80
    assert data["sync"]["funding"]["status"] == "fresh"
    assert data["sync"]["funding"]["complete"] is True
    assert data["sync"]["funding"].get("reason") is None
    ids = {row["exchange_entry_id"] for row in data["funding"]}
    assert len(ids) == 80
    # Must have advanced with snake_case page_num (not stuck on page 1).
    assert [r.get("page_num") for r in exchange.requests] == [1, 2, 3, 4]
    assert all("pageNum" in r and "page_num" in r for r in exchange.requests)


async def test_funding_duplicate_pages_do_not_inflate_complete_count():
    """If page_num is ignored and every page repeats, do not claim complete@totalCount."""
    from backend.services.exchange_service import fetch_history
    from backend.tests.fixtures.phase2b_ledger import funding_row

    page1 = [funding_row(f"dup-{i}", funding=f"-0.0{i}", offset=i) for i in range(20)]

    class StuckOnPage1(SnakeOnlyFundingExchange):
        def contract_private_get_position_funding_records(self, params):
            # Ignore all page params — always return the first page, totalPage=4.
            self.requests.append(dict(params))
            return {
                "success": True,
                "data": {
                    "pageSize": 20,
                    "totalCount": 80,
                    "totalPage": 4,
                    "currentPage": 1,
                    "resultList": page1,
                },
            }

    exchange = _attach_empty_position_order(StuckOnPage1([[]]))

    data = await fetch_history(exchange, user_id=9)

    assert len(data["funding"]) == 20  # unique only
    assert data["sync"]["funding"]["rows_fetched_total"] == 20
    assert data["sync"]["funding"]["source_total"] == 80
    assert data["sync"]["funding"]["complete"] is False
    assert data["sync"]["funding"]["status"] == "partial"
    assert data["sync"]["funding"]["reason"] == "pagination_not_advancing"
