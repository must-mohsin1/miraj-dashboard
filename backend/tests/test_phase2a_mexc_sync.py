"""Phase 2A MEXC exchange sync tests.

These tests use static redacted fixtures and never call a live MEXC endpoint.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import func, select

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import ExchangeSyncState, FuturesAccountSnapshot, OrderHistory, PortfolioBalance, PositionHistory, User
from backend.services.exchange_service import _fetch_positions_history, fetch_history, fetch_portfolio
from backend.tests.fixtures.phase2a_mexc import (
    FUTURES_ACCOUNT_ASSETS,
    MEXC_510_REDACTED_ERROR,
    MUTATED_ORDER,
    MUTATED_POSITION,
    ORDER_HISTORY_225,
    PARTIAL_CLOSE_DUPLICATES,
    POSITION_HISTORY_237,
    history_order,
    history_position,
    paged_rows,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="phase2a_mexc_sync_")
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


async def _user(session, username: str = "phase2async") -> User:
    user = User(
        username=username,
        email=f"{username}@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


class MockMexcExchange:
    id = "mexc"
    markets = {"BTCUSDT": {"contractSize": 1}, "ETHUSDT": {"contractSize": 1}}

    def __init__(
        self,
        *,
        position_pages: list[list[dict]] | dict[str, Any] | None = None,
        order_pages: list[list[dict]] | dict[str, Any] | None = None,
        account_assets: dict | None = FUTURES_ACCOUNT_ASSETS,
    ) -> None:
        self.position_pages = position_pages if position_pages is not None else []
        self.order_pages = order_pages if order_pages is not None else []
        self.account_assets = account_assets
        self.position_page_requests: list[int] = []
        self.order_page_requests: list[int] = []

    def load_markets(self):
        return self.markets

    def fetchBalance(self):
        return {}

    def fetchPositions(self):
        return []

    def contract_private_get_position_list_history_positions(self, params: dict):
        self.position_page_requests.append(params["pageNum"])
        return self._page_response(self.position_pages, params["pageNum"])

    def contract_private_get_order_list_history_orders(self, params: dict):
        self.order_page_requests.append(params["pageNum"])
        return self._page_response(self.order_pages, params["pageNum"])

    def contract_private_get_account_assets(self, params: dict | None = None):
        return self.account_assets

    @staticmethod
    def _page_response(pages: list[list[dict]] | dict[str, Any], page_num: int) -> dict:
        if isinstance(pages, dict):
            return pages
        page = pages[page_num - 1] if page_num <= len(pages) else []
        return {
            "success": True,
            "data": {
                "list": page,
                "totalPage": len(pages),
                "total": sum(len(p) for p in pages),
                "pageNum": page_num,
                "pageSize": 100,
            },
        }


def test_phase2a_fixtures_are_static_redacted_and_separate_from_phase1_contract():
    assert len(POSITION_HISTORY_237) == 237
    assert len(ORDER_HISTORY_225) == 225
    assert "apiKey" not in repr(POSITION_HISTORY_237)
    assert "secret" not in repr(ORDER_HISTORY_225).lower()


async def test_fetch_history_exhausts_mexc_pages_beyond_200_and_returns_source_ids_and_coverage():
    exchange = MockMexcExchange(
        position_pages=paged_rows(POSITION_HISTORY_237),
        order_pages=paged_rows(ORDER_HISTORY_225),
    )

    data = await fetch_history(exchange, user_id=7)

    assert exchange.position_page_requests == [1, 2, 3]
    assert exchange.order_page_requests == [1, 2, 3]
    assert len(data["position_history"]) == 237
    assert len(data["order_history"]) == 225
    assert data["position_history"][0]["exchange_position_id"].startswith("redacted-pos-")
    assert data["order_history"][0]["exchange_order_id"].startswith("redacted-order-")
    assert data["sync"]["positions_history"]["complete"] is True
    assert data["sync"]["positions_history"]["cursor"] == {"page_num": 3, "page_size": 100, "exhausted": True}
    assert data["sync"]["positions_history"]["rows_fetched_total"] == 237
    assert data["sync"]["orders_history"]["source_total"] == 225


async def test_phase2a_position_normaliser_does_not_infer_liquidation_from_negative_roi():
    row = history_position("negative-roi-without-close-reason", pnl="-95.0")
    row["profitRatio"] = "-0.95"
    exchange = MockMexcExchange(position_pages=[[row]], order_pages=[])

    data = await fetch_history(exchange, user_id=7)

    assert data["position_history"][0]["pnl_percent"] == -95.0
    assert data["position_history"][0]["reported_roi_pct"] == -95.0
    assert data["position_history"][0]["close_reason"] == "closed"


def test_legacy_positions_history_does_not_infer_liquidation_from_negative_roi():
    row = history_position("legacy-negative-roi-without-close-reason", pnl="-95.0")
    row["profitRatio"] = "-0.95"
    exchange = MockMexcExchange(position_pages=[[row]], order_pages=[])

    positions = _fetch_positions_history(exchange, user_id=7, exchange_name="mexc")

    assert positions[0]["pnl_percent"] == -95.0
    assert positions[0]["close_reason"] == "closed"


async def test_phase2a_upsert_is_source_id_idempotent_and_stream_state_isolated(session):
    from backend.services.phase2a_sync import persist_phase2a_sync_payload

    user = await _user(session)
    now = datetime(2026, 7, 26, 1, 0, 0)
    first_payload = {
        "position_history": [*PARTIAL_CLOSE_DUPLICATES],
        "order_history": [history_order("same-order-id", offset=999), history_order("same-order-id", offset=999)],
        "futures_account": FUTURES_ACCOUNT_ASSETS["data"][0],
        "sync": {
            "positions_history": {"status": "fresh", "complete": True, "cursor": {"page_num": 1, "exhausted": True}, "rows_fetched_total": 2, "source_total": 2},
            "orders_history": {"status": "error", "complete": False, "reason": "rate_limit", "error_code": "510", "error_message": "rate limited for REDACTED synthetic-key value"},
            "futures_account_assets": {"status": "fresh", "complete": True, "rows_fetched_total": 1, "source_total": 1},
        },
    }

    await persist_phase2a_sync_payload(session, user.id, "mexc", first_payload, now)
    await session.commit()
    await persist_phase2a_sync_payload(
        session,
        user.id,
        "mexc",
        {
            **first_payload,
            "position_history": [MUTATED_POSITION, PARTIAL_CLOSE_DUPLICATES[1]],
            "order_history": [MUTATED_ORDER],
            "sync": {
                "orders_history": {"status": "fresh", "complete": True, "cursor": {"page_num": 1, "exhausted": True}, "rows_fetched_total": 1, "source_total": 1},
            },
        },
        now,
    )
    await session.commit()

    assert await session.scalar(select(func.count()).select_from(PositionHistory)) == 2
    assert await session.scalar(select(func.count()).select_from(OrderHistory)) == 1
    assert await session.scalar(select(func.count()).select_from(FuturesAccountSnapshot)) == 1
    assert await session.scalar(select(func.count()).select_from(ExchangeSyncState)) == 3

    updated_pos = await session.scalar(select(PositionHistory).where(PositionHistory.exchange_position_id == "partial-close-a"))
    updated_order = await session.scalar(select(OrderHistory).where(OrderHistory.exchange_order_id == "same-order-id"))
    positions_state = await session.scalar(select(ExchangeSyncState).where(ExchangeSyncState.stream == "positions_history"))
    orders_state = await session.scalar(select(ExchangeSyncState).where(ExchangeSyncState.stream == "orders_history"))

    assert updated_pos.pnl == 9.99
    assert updated_pos.reported_pnl == 9.99
    assert updated_order.price == 123.45
    assert positions_state.status == "fresh"
    assert positions_state.cursor_json == {"page_num": 1, "exhausted": True}
    assert orders_state.status == "fresh"


async def test_futures_account_snapshot_does_not_fall_back_to_spot_balances(session):
    from backend.services.phase2a_sync import latest_futures_account_snapshot, persist_phase2a_sync_payload

    user = await _user(session, "phase2aspot")
    session.add(PortfolioBalance(user_id=user.id, exchange="mexc", asset="USDT", free=500.0, locked=0.0, total=500.0, usd_value=500.0))
    await session.commit()

    assert await latest_futures_account_snapshot(session, user.id, "mexc") is None

    data = await fetch_portfolio(MockMexcExchange(account_assets=FUTURES_ACCOUNT_ASSETS), user_id=user.id)
    await persist_phase2a_sync_payload(session, user.id, "mexc", data, datetime(2026, 7, 26, 1, 30, 0))
    await session.commit()

    snapshot = await latest_futures_account_snapshot(session, user.id, "mexc")
    assert snapshot is not None
    assert snapshot.equity == 1234.56
    assert snapshot.available_balance == 1000.25
    assert snapshot.position_margin == 88.8


async def test_mexc_510_rate_limit_records_redacted_error_coverage(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []
    monkeypatch.setattr("backend.services.exchange_service.time.sleep", sleeps.append)
    exchange = MockMexcExchange(
        position_pages=paged_rows(POSITION_HISTORY_237[:3]),
        order_pages=MEXC_510_REDACTED_ERROR,
    )

    data = await fetch_history(exchange, user_id=7)

    assert len(data["position_history"]) == 3
    assert data["sync"]["positions_history"]["status"] == "fresh"
    assert data["sync"]["orders_history"]["status"] == "error"
    assert data["sync"]["orders_history"]["complete"] is False
    assert data["sync"]["orders_history"]["error_code"] == "510"
    assert "synthetic-key" not in data["sync"]["orders_history"]["error_message"]
    assert len(sleeps) == 3
    assert max(sleeps) <= 4.0
