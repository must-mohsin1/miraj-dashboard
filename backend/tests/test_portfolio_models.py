"""Tests for the 5 new portfolio DB models (P4-T-B).

Run with::

    cd <project-root>
    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_portfolio_models.py -v

Tests use an isolated temporary SQLite database file per test.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from typing import AsyncGenerator

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force JWT secret (required by backend.auth at import time — even though we
# don't call auth directly, the import chain may touch it)
if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.auth import hash_password
from backend.database import Base, get_session, set_db_path
from backend.models import (
    ExchangeKey,
    PortfolioBalance,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioTrade,
    User,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


pytestmark = pytest.mark.anyio


@pytest.fixture
def tmp_db_path() -> str:
    """Yield a unique temporary DB path per test, cleaned up after."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="portfolio_model_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def session(tmp_db_path: str):
    """Yield an async session backed by a fresh DB with all tables."""
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
    """Create and return a test user."""
    user = User(
        username="portfoliouser",
        email="portfolio@test.com",
        hashed_password=hash_password("testpass123"),
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


# ── ExchangeKey tests (AC-1) ─────────────────────────────────────────────────


class TestExchangeKey:
    async def test_create_exchange_key(self, session, user: User) -> None:
        """Create an exchange key and verify all columns."""
        key = ExchangeKey(
            user_id=user.id,
            exchange="binance",
            api_key_encrypted=b"encrypted_key_123",
            api_secret_encrypted=b"encrypted_secret_456",
        )
        session.add(key)
        await session.flush()
        await session.refresh(key)

        assert key.id is not None
        assert key.user_id == user.id
        assert key.exchange == "binance"
        assert key.api_key_encrypted == b"encrypted_key_123"
        assert key.api_secret_encrypted == b"encrypted_secret_456"
        assert key.created_at is not None
        assert key.updated_at is not None

    async def test_exchange_key_unique_constraint(self, session, user: User) -> None:
        """Inserting a duplicate (user_id, exchange) must raise IntegrityError."""
        key1 = ExchangeKey(
            user_id=user.id,
            exchange="binance",
            api_key_encrypted=b"key1",
            api_secret_encrypted=b"sec1",
        )
        session.add(key1)
        await session.flush()

        key2 = ExchangeKey(
            user_id=user.id,
            exchange="binance",
            api_key_encrypted=b"key2",
            api_secret_encrypted=b"sec2",
        )
        session.add(key2)
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_exchange_key_different_exchange_allowed(self, session, user: User) -> None:
        """Same user can have keys for different exchanges."""
        key1 = ExchangeKey(
            user_id=user.id,
            exchange="binance",
            api_key_encrypted=b"key1",
            api_secret_encrypted=b"sec1",
        )
        key2 = ExchangeKey(
            user_id=user.id,
            exchange="bybit",
            api_key_encrypted=b"key2",
            api_secret_encrypted=b"sec2",
        )
        session.add_all([key1, key2])
        await session.flush()
        # No exception = constraint not violated for different exchanges

    async def test_exchange_key_cascade_delete(self, session, user: User) -> None:
        """Deleting the user must cascade-delete their exchange keys."""
        key = ExchangeKey(
            user_id=user.id,
            exchange="binance",
            api_key_encrypted=b"key",
            api_secret_encrypted=b"sec",
        )
        session.add(key)
        await session.flush()

        await session.delete(user)
        await session.flush()

        result = await session.execute(
            select(ExchangeKey).where(ExchangeKey.exchange == "binance")
        )
        assert result.scalar_one_or_none() is None

    async def test_exchange_key_relationship(self, session, user: User) -> None:
        """user.exchange_keys returns related keys."""
        key = ExchangeKey(
            user_id=user.id,
            exchange="binance",
            api_key_encrypted=b"key",
            api_secret_encrypted=b"sec",
        )
        session.add(key)
        await session.flush()
        await session.refresh(user, attribute_names=["exchange_keys"])

        keys = user.exchange_keys
        assert len(keys) == 1
        assert keys[0].exchange == "binance"


# ── PortfolioBalance tests (AC-2) ────────────────────────────────────────────


class TestPortfolioBalance:
    async def test_create_balance(self, session, user: User) -> None:
        """Create a portfolio balance and verify all columns."""
        bal = PortfolioBalance(
            user_id=user.id,
            exchange="binance",
            asset="BTC",
            free=1.5,
            locked=0.5,
            total=2.0,
        )
        session.add(bal)
        await session.flush()
        await session.refresh(bal)

        assert bal.id is not None
        assert bal.user_id == user.id
        assert bal.exchange == "binance"
        assert bal.asset == "BTC"
        assert bal.free == 1.5
        assert bal.locked == 0.5
        assert bal.total == 2.0
        assert bal.updated_at is not None

    async def test_balance_cascade_delete(self, session, user: User) -> None:
        """Deleting the user must cascade-delete their balances."""
        bal = PortfolioBalance(
            user_id=user.id,
            exchange="binance",
            asset="ETH",
            free=10.0,
            locked=0.0,
            total=10.0,
        )
        session.add(bal)
        await session.flush()

        await session.delete(user)
        await session.flush()

        result = await session.execute(
            select(PortfolioBalance).where(PortfolioBalance.asset == "ETH")
        )
        assert result.scalar_one_or_none() is None

    async def test_balance_indexed_on_user_exchange(self, session, user: User) -> None:
        """The (user_id, exchange) index exists (verify via table info)."""
        # Use SQLite PRAGMA to check for the index
        result = await session.execute(
            text("PRAGMA index_list('portfolio_balances')")
        )
        index_names = [row[1] for row in result.fetchall()]
        # One of the index names should reference user_id and exchange
        assert any("user_id" in name or "exchange" in name for name in index_names), (
            f"No index found on portfolio_balances; indices: {index_names}"
        )

    async def test_balance_relationship(self, session, user: User) -> None:
        """user.portfolio_balances returns related balances."""
        bal = PortfolioBalance(
            user_id=user.id,
            exchange="binance",
            asset="BTC",
            free=1.0,
            locked=0.0,
            total=1.0,
        )
        session.add(bal)
        await session.flush()
        await session.refresh(user, attribute_names=["portfolio_balances"])

        assert len(user.portfolio_balances) == 1
        assert user.portfolio_balances[0].asset == "BTC"


# ── PortfolioPosition tests (AC-3) ───────────────────────────────────────────


class TestPortfolioPosition:
    async def test_create_position(self, session, user: User) -> None:
        """Create a portfolio position and verify all columns."""
        pos = PortfolioPosition(
            user_id=user.id,
            exchange="binance",
            symbol="BTCUSDT",
            side="long",
            size=0.5,
            entry_price=60000.0,
            mark_price=61000.0,
            pnl=500.0,
            pnl_percent=1.67,
            leverage=10.0,
            liquidation_price=55000.0,
            margin=3000.0,
        )
        session.add(pos)
        await session.flush()
        await session.refresh(pos)

        assert pos.id is not None
        assert pos.user_id == user.id
        assert pos.exchange == "binance"
        assert pos.symbol == "BTCUSDT"
        assert pos.side == "long"
        assert pos.size == 0.5
        assert pos.entry_price == 60000.0
        assert pos.mark_price == 61000.0
        assert pos.pnl == 500.0
        assert pos.pnl_percent == 1.67
        assert pos.leverage == 10.0
        assert pos.liquidation_price == 55000.0
        assert pos.margin == 3000.0
        assert pos.updated_at is not None

    async def test_position_nullable_liquidation_price(self, session, user: User) -> None:
        """liquidation_price can be NULL for spot or cross-margin positions."""
        pos = PortfolioPosition(
            user_id=user.id,
            exchange="binance",
            symbol="ETHUSDT",
            side="short",
            size=2.0,
            entry_price=3000.0,
            mark_price=3100.0,
            pnl=-200.0,
            pnl_percent=-3.33,
            leverage=5.0,
            liquidation_price=None,
            margin=1200.0,
        )
        session.add(pos)
        await session.flush()
        await session.refresh(pos)

        assert pos.liquidation_price is None

    async def test_position_cascade_delete(self, session, user: User) -> None:
        """Deleting the user must cascade-delete their positions."""
        pos = PortfolioPosition(
            user_id=user.id,
            exchange="binance",
            symbol="ETHUSDT",
            side="long",
            size=1.0,
            entry_price=3000.0,
            mark_price=3100.0,
            pnl=100.0,
            pnl_percent=3.33,
            leverage=5.0,
            margin=600.0,
        )
        session.add(pos)
        await session.flush()

        await session.delete(user)
        await session.flush()

        result = await session.execute(
            select(PortfolioPosition).where(PortfolioPosition.symbol == "ETHUSDT")
        )
        assert result.scalar_one_or_none() is None

    async def test_position_relationship(self, session, user: User) -> None:
        """user.portfolio_positions returns related positions."""
        pos = PortfolioPosition(
            user_id=user.id,
            exchange="binance",
            symbol="DOGEUSDT",
            side="long",
            size=1000.0,
            entry_price=0.12,
            mark_price=0.13,
            pnl=10.0,
            pnl_percent=8.33,
            leverage=1.0,
            margin=120.0,
        )
        session.add(pos)
        await session.flush()
        await session.refresh(user, attribute_names=["portfolio_positions"])

        assert len(user.portfolio_positions) == 1
        assert user.portfolio_positions[0].symbol == "DOGEUSDT"


# ── PortfolioTrade tests (AC-4) ──────────────────────────────────────────────


class TestPortfolioTrade:
    async def test_create_trade(self, session, user: User) -> None:
        """Create a portfolio trade and verify all columns."""
        ts = datetime(2024, 6, 15, 10, 30, 0)
        trade = PortfolioTrade(
            user_id=user.id,
            exchange="binance",
            symbol="BTCUSDT",
            side="buy",
            type="limit",
            price=60000.0,
            amount=0.1,
            cost=6000.0,
            fee=6.0,
            fee_currency="BNB",
            timestamp=ts,
            exchange_trade_id="abc123",
        )
        session.add(trade)
        await session.flush()
        await session.refresh(trade)

        assert trade.id is not None
        assert trade.user_id == user.id
        assert trade.exchange == "binance"
        assert trade.symbol == "BTCUSDT"
        assert trade.side == "buy"
        assert trade.type == "limit"
        assert trade.price == 60000.0
        assert trade.amount == 0.1
        assert trade.cost == 6000.0
        assert trade.fee == 6.0
        assert trade.fee_currency == "BNB"
        assert trade.timestamp == ts
        assert trade.exchange_trade_id == "abc123"

    async def test_trade_nullable_fee_fields(self, session, user: User) -> None:
        """fee and fee_currency are nullable."""
        ts = datetime(2024, 6, 15, 10, 30, 0)
        trade = PortfolioTrade(
            user_id=user.id,
            exchange="binance",
            symbol="ETHUSDT",
            side="sell",
            type="market",
            price=3000.0,
            amount=0.5,
            cost=1500.0,
            fee=None,
            fee_currency=None,
            timestamp=ts,
            exchange_trade_id="def456",
        )
        session.add(trade)
        await session.flush()
        await session.refresh(trade)

        assert trade.fee is None
        assert trade.fee_currency is None

    async def test_trade_unique_constraint(self, session, user: User) -> None:
        """Duplicate (exchange, exchange_trade_id, user_id) must raise IntegrityError."""
        ts = datetime(2024, 6, 15, 10, 30, 0)
        trade1 = PortfolioTrade(
            user_id=user.id,
            exchange="binance",
            symbol="BTCUSDT",
            side="buy",
            type="limit",
            price=60000.0,
            amount=0.1,
            cost=6000.0,
            timestamp=ts,
            exchange_trade_id="duplicate_id",
        )
        session.add(trade1)
        await session.flush()

        trade2 = PortfolioTrade(
            user_id=user.id,
            exchange="binance",
            symbol="BTCUSDT",
            side="buy",
            type="limit",
            price=60001.0,
            amount=0.2,
            cost=12000.0,
            timestamp=ts,
            exchange_trade_id="duplicate_id",
        )
        session.add(trade2)
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_trade_cascade_delete(self, session, user: User) -> None:
        """Deleting the user must cascade-delete their trades."""
        ts = datetime(2024, 6, 15, 10, 30, 0)
        trade = PortfolioTrade(
            user_id=user.id,
            exchange="binance",
            symbol="BTCUSDT",
            side="buy",
            type="limit",
            price=60000.0,
            amount=0.1,
            cost=6000.0,
            timestamp=ts,
            exchange_trade_id="ghi789",
        )
        session.add(trade)
        await session.flush()

        await session.delete(user)
        await session.flush()

        result = await session.execute(
            select(PortfolioTrade).where(PortfolioTrade.exchange_trade_id == "ghi789")
        )
        assert result.scalar_one_or_none() is None

    async def test_trade_relationship(self, session, user: User) -> None:
        """user.portfolio_trades returns related trades."""
        ts = datetime(2024, 6, 15, 10, 30, 0)
        trade = PortfolioTrade(
            user_id=user.id,
            exchange="binance",
            symbol="SOLUSDT",
            side="buy",
            type="market",
            price=150.0,
            amount=10.0,
            cost=1500.0,
            timestamp=ts,
            exchange_trade_id="jkl012",
        )
        session.add(trade)
        await session.flush()
        await session.refresh(user, attribute_names=["portfolio_trades"])

        assert len(user.portfolio_trades) == 1
        assert user.portfolio_trades[0].symbol == "SOLUSDT"


# ── PortfolioSnapshot tests (AC-5) ───────────────────────────────────────────


class TestPortfolioSnapshot:
    async def test_create_snapshot(self, session, user: User) -> None:
        """Create a portfolio snapshot and verify all columns."""
        ts = datetime(2024, 6, 15, 12, 0, 0)
        snap = PortfolioSnapshot(
            user_id=user.id,
            exchange="binance",
            total_balance_usd=50000.0,
            total_pnl_usd=1500.0,
            open_positions=3,
            timestamp=ts,
        )
        session.add(snap)
        await session.flush()
        await session.refresh(snap)

        assert snap.id is not None
        assert snap.user_id == user.id
        assert snap.exchange == "binance"
        assert snap.total_balance_usd == 50000.0
        assert snap.total_pnl_usd == 1500.0
        assert snap.open_positions == 3
        assert snap.timestamp == ts

    async def test_snapshot_nullable_total_balance(self, session, user: User) -> None:
        """total_balance_usd can be NULL (e.g. exchange API failure)."""
        ts = datetime(2024, 6, 15, 12, 0, 0)
        snap = PortfolioSnapshot(
            user_id=user.id,
            exchange="binance",
            total_balance_usd=None,
            total_pnl_usd=500.0,
            open_positions=1,
            timestamp=ts,
        )
        session.add(snap)
        await session.flush()
        await session.refresh(snap)

        assert snap.total_balance_usd is None

    async def test_snapshot_cascade_delete(self, session, user: User) -> None:
        """Deleting the user must cascade-delete their snapshots."""
        ts = datetime(2024, 6, 15, 12, 0, 0)
        snap = PortfolioSnapshot(
            user_id=user.id,
            exchange="binance",
            total_pnl_usd=100.0,
            open_positions=0,
            timestamp=ts,
        )
        session.add(snap)
        await session.flush()

        await session.delete(user)
        await session.flush()

        result = await session.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.exchange == "binance")
        )
        assert result.scalar_one_or_none() is None

    async def test_snapshot_relationship(self, session, user: User) -> None:
        """user.portfolio_snapshots returns related snapshots."""
        ts = datetime(2024, 6, 15, 12, 0, 0)
        snap = PortfolioSnapshot(
            user_id=user.id,
            exchange="bybit",
            total_pnl_usd=200.0,
            open_positions=2,
            timestamp=ts,
        )
        session.add(snap)
        await session.flush()
        await session.refresh(user, attribute_names=["portfolio_snapshots"])

        assert len(user.portfolio_snapshots) == 1
        assert user.portfolio_snapshots[0].exchange == "bybit"


# ── User relationship integration tests ──────────────────────────────────────


class TestUserRelationships:
    """Verify all 5 new backrefs exist on User."""

    async def test_user_has_all_portfolio_relationships(self) -> None:
        """User model has all 5 new relationship attributes (even if empty)."""
        from sqlalchemy.orm import class_mapper

        mapper = class_mapper(User)
        rel_names = {r.key for r in mapper.relationships}

        assert "exchange_keys" in rel_names
        assert "portfolio_balances" in rel_names
        assert "portfolio_positions" in rel_names
        assert "portfolio_trades" in rel_names
        assert "portfolio_snapshots" in rel_names
