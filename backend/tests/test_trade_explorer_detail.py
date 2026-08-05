"""Trade Explorer detail — orders window, scan attribution, journal links."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

from backend import database
from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import Analysis, OrderHistory, PositionHistory, TradeJournalEntry, User
from backend.services import analytics_service

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="trade_explorer_detail_")
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


@pytest.fixture
async def user(session) -> User:
    user = User(
        username="tradedetail",
        email="tradedetail@test.local",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    return user


async def test_trade_explorer_detail_orders_scan_journal(session, user: User):
    open_t = datetime(2026, 7, 24, 10, 0, 0)
    close_t = datetime(2026, 7, 24, 12, 0, 0)
    position = PositionHistory(
        user_id=user.id,
        exchange="mexc",
        symbol="BTC_USDT",
        side="long",
        size=12,
        entry_price=100.0,
        exit_price=101.0,
        pnl=1.05,
        pnl_percent=0.89,
        leverage=20,
        open_time=open_t,
        close_time=close_t,
        close_reason="manual",
        contract_size=0.001,
    )
    session.add(position)
    await session.flush()

    # Matching order (same symbol key, inside window)
    session.add(
        OrderHistory(
            user_id=user.id,
            exchange="mexc",
            symbol="BTCUSDT",
            type="market",
            side="buy",
            side_action="Open Long",
            price=100.0,
            amount=12,
            filled=12,
            filled_price=100.0,
            cost=1200.0,
            status="filled",
            timestamp=open_t + timedelta(minutes=1),
            fee=0.02,
            fee_currency="USDT",
            exchange_order_id="ord-1",
        )
    )
    # Different symbol — must not match
    session.add(
        OrderHistory(
            user_id=user.id,
            exchange="mexc",
            symbol="ETHUSDT",
            type="market",
            side="buy",
            price=1.0,
            amount=1,
            filled=1,
            cost=1.0,
            status="filled",
            timestamp=open_t + timedelta(minutes=2),
            fee=0.01,
            exchange_order_id="ord-eth",
        )
    )
    # Pre-entry scan
    import json

    session.add(
        Analysis(
            user_id=user.id,
            pair="BTC-USD",
            analysis_type="scan",
            result=json.dumps(
                {
                    "confluence_score": 22.5,
                    "trade_plan_flat": {"direction": "LONG"},
                    "qqe_signals": {"daily": {"trend": "up", "strength": "strong"}},
                }
            ),
            created_at=open_t - timedelta(hours=1),
        )
    )
    session.add(
        TradeJournalEntry(
            user_id=user.id,
            exchange="mexc",
            symbol="BTC_USDT",
            position_id=position.id,
            notes="Took the breakout",
            tags="long,breakout",
        )
    )
    await session.commit()

    detail = await analytics_service.get_trade_explorer_detail(
        session, user.id, "mexc", position.id
    )

    assert detail["position"]["id"] == position.id
    assert detail["position"]["symbol"] == "BTC_USDT"
    assert detail["orders_match"]["count"] == 1
    assert detail["orders"][0]["exchange_order_id"] == "ord-1"
    assert detail["orders"][0]["fee"] == 0.02
    assert detail["fees"]["sum_order_fees"] == 0.02
    assert detail["scan"]["found"] is True
    assert detail["scan"]["score"] == 22.5
    assert detail["scan"]["direction"] == "LONG"
    assert detail["scan"]["href_path"] == "/analysis/BTC-USD"
    assert detail["journal"]["count"] == 1
    assert detail["journal"]["entries"][0]["tags"] == "long,breakout"
    assert "fee_net_pnl" in detail["unavailable"]


async def test_trade_explorer_detail_not_found(session, user: User):
    with pytest.raises(LookupError):
        await analytics_service.get_trade_explorer_detail(session, user.id, "mexc", 99999)


async def test_trade_explorer_detail_empty_related(session, user: User):
    position = PositionHistory(
        user_id=user.id,
        exchange="mexc",
        symbol="SOL_USDT",
        side="short",
        size=1,
        entry_price=50.0,
        exit_price=49.0,
        pnl=1.0,
        pnl_percent=2.0,
        leverage=5,
        open_time=datetime(2026, 7, 1, 0, 0, 0),
        close_time=datetime(2026, 7, 1, 1, 0, 0),
        close_reason="closed",
    )
    session.add(position)
    await session.commit()

    detail = await analytics_service.get_trade_explorer_detail(
        session, user.id, "mexc", position.id
    )
    assert detail["orders"] == []
    assert detail["orders_match"]["reason"] == "no_orders_in_symbol_time_window"
    assert detail["scan"]["found"] is False
    assert detail["journal"]["count"] == 0
