"""Tests for DCA shadow validation persistence models.

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_dca_validation_models.py -v

Tests use isolated SQLite metadata and database files.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import inspect, select

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.auth import hash_password
from backend.database import Base, set_db_path
from backend.models import (
    DcaShadowDecisionHistory,
    DcaShadowGlobalKillSwitch,
    DcaShadowSymbolKillSwitch,
    DcaShadowUserKillSwitch,
    PortfolioPosition,
    User,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


pytestmark = pytest.mark.anyio


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="dca_validation_model_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def session(tmp_db_path: str):
    from backend import database

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
        username="dcauser",
        email="dcauser@test.com",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def test_dca_shadow_tables_create_with_isolated_sqlite_metadata(session) -> None:
    bind = session.get_bind()
    table_names = await session.run_sync(lambda sync_session: inspect(sync_session.bind).get_table_names())

    assert "dca_shadow_global_kill_switches" in table_names
    assert "dca_shadow_user_kill_switches" in table_names
    assert "dca_shadow_symbol_kill_switches" in table_names
    assert "dca_shadow_decision_history" in table_names
    assert "portfolio_positions" in table_names
    assert bind is not None


async def test_user_symbol_and_global_shadow_add_kill_switches_persist(session, user: User) -> None:
    global_switch = DcaShadowGlobalKillSwitch(
        active=True,
        reason="market incident",
        created_by="ops",
    )
    user_switch = DcaShadowUserKillSwitch(
        user_id=user.id,
        active=True,
        reason="user paused DCA adds",
    )
    symbol_switch = DcaShadowSymbolKillSwitch(
        user_id=user.id,
        exchange="mexc",
        symbol="BTCUSDT",
        active=True,
        reason="symbol cooldown",
    )

    session.add_all([global_switch, user_switch, symbol_switch])
    await session.flush()
    await session.refresh(user, attribute_names=["dca_shadow_user_kill_switches", "dca_shadow_symbol_kill_switches"])

    assert global_switch.id is not None
    assert global_switch.active is True
    assert global_switch.reason == "market incident"
    assert global_switch.created_at is not None
    assert global_switch.updated_at is not None
    assert len(user.dca_shadow_user_kill_switches) == 1
    assert user.dca_shadow_user_kill_switches[0].reason == "user paused DCA adds"
    assert len(user.dca_shadow_symbol_kill_switches) == 1
    assert user.dca_shadow_symbol_kill_switches[0].symbol == "BTCUSDT"


async def test_shadow_decision_history_preserves_audit_fields(session, user: User) -> None:
    decided_at = datetime(2026, 7, 13, 12, 30, 0)
    gate_breakdown = {
        "dca_safe": {"passed": True, "reason": "checklist passed"},
        "symbol_kill_switch": {"passed": False, "reason": "BTCUSDT disabled"},
    }
    blocked_gates = ["symbol_kill_switch"]
    assumption_set = {"fee_pct": 0.0004, "slippage_pct": 0.0005, "max_adds_per_hour": 3}

    history = DcaShadowDecisionHistory(
        user_id=user.id,
        timestamp=decided_at,
        exchange="mexc",
        symbol="BTCUSDT",
        original_recommendation="ADD",
        final_outcome="would_block",
        gate_breakdown=gate_breakdown,
        blocked_gates=blocked_gates,
        assumption_set=assumption_set,
        final_reason="ADD blocked because the symbol kill switch is active.",
    )

    session.add(history)
    await session.flush()
    await session.refresh(history)

    assert history.id is not None
    assert history.user_id == user.id
    assert history.timestamp == decided_at
    assert history.exchange == "mexc"
    assert history.symbol == "BTCUSDT"
    assert history.original_recommendation == "ADD"
    assert history.final_outcome == "would_block"
    assert history.gate_breakdown == gate_breakdown
    assert history.blocked_gates == blocked_gates
    assert history.assumption_set == assumption_set
    assert history.final_reason == "ADD blocked because the symbol kill switch is active."


async def test_shadow_relationships_cascade_without_affecting_existing_portfolio_models(session, user: User) -> None:
    position = PortfolioPosition(
        user_id=user.id,
        exchange="mexc",
        symbol="ETHUSDT",
        side="long",
        size=1.0,
        entry_price=3000.0,
        mark_price=3050.0,
        pnl=50.0,
        pnl_percent=1.67,
        leverage=3.0,
        margin=1000.0,
    )
    user_switch = DcaShadowUserKillSwitch(user_id=user.id, active=True, reason="paused")
    symbol_switch = DcaShadowSymbolKillSwitch(
        user_id=user.id,
        exchange="mexc",
        symbol="ETHUSDT",
        active=True,
        reason="paused symbol",
    )
    history = DcaShadowDecisionHistory(
        user_id=user.id,
        timestamp=datetime(2026, 7, 13, 12, 45, 0),
        exchange="mexc",
        symbol="ETHUSDT",
        original_recommendation="ADD",
        final_outcome="would_block",
        gate_breakdown={"user_kill_switch": {"passed": False}},
        blocked_gates=["user_kill_switch"],
        assumption_set={"fee_pct": 0.0004},
        final_reason="User kill switch is active.",
    )
    session.add_all([position, user_switch, symbol_switch, history])
    await session.flush()

    await session.refresh(user, attribute_names=[
        "portfolio_positions",
        "dca_shadow_user_kill_switches",
        "dca_shadow_symbol_kill_switches",
        "dca_shadow_decision_history",
    ])
    assert len(user.portfolio_positions) == 1
    assert len(user.dca_shadow_user_kill_switches) == 1
    assert len(user.dca_shadow_symbol_kill_switches) == 1
    assert len(user.dca_shadow_decision_history) == 1

    await session.delete(user)
    await session.flush()

    for model in (PortfolioPosition, DcaShadowUserKillSwitch, DcaShadowSymbolKillSwitch, DcaShadowDecisionHistory):
        result = await session.execute(select(model))
        assert result.scalars().all() == []
