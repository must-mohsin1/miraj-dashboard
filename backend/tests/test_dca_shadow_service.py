"""Tests for non-live DCA shadow-mode safety gates and audit logging."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import pytest
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

pytestmark = pytest.mark.anyio


class ShadowTestBase(DeclarativeBase):
    pass


class FakeDcaShadowGlobalKillSwitch(ShadowTestBase):
    __tablename__ = "test_dca_shadow_global_kill_switches"

    id = Column(Integer, primary_key=True)
    active = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FakeDcaShadowUserKillSwitch(ShadowTestBase):
    __tablename__ = "test_dca_shadow_user_kill_switches"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FakeDcaShadowSymbolKillSwitch(ShadowTestBase):
    __tablename__ = "test_dca_shadow_symbol_kill_switches"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    symbol = Column(String(40), nullable=False)
    active = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FakeDcaShadowDecisionHistory(ShadowTestBase):
    __tablename__ = "test_dca_shadow_decision_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    exchange = Column(String(32), nullable=False)
    symbol = Column(String(40), nullable=False)
    original_recommendation = Column(String(20), nullable=False)
    final_outcome = Column(String(20), nullable=False)
    gate_breakdown = Column(JSON, nullable=False)
    blocked_gates = Column(JSON, nullable=False)
    assumption_set = Column(JSON, nullable=False)
    final_reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncSession, None]:
    import backend.services.dca_shadow_service as service

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(ShadowTestBase.metadata.create_all)

    monkeypatch.setattr(service, "DcaShadowGlobalKillSwitch", FakeDcaShadowGlobalKillSwitch)
    monkeypatch.setattr(service, "DcaShadowUserKillSwitch", FakeDcaShadowUserKillSwitch)
    monkeypatch.setattr(service, "DcaShadowSymbolKillSwitch", FakeDcaShadowSymbolKillSwitch)
    monkeypatch.setattr(service, "DcaShadowDecisionHistory", FakeDcaShadowDecisionHistory)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()


def _scan(*, score: float = 12.0, dca_safe: bool = True) -> dict:
    return {
        "confluence_score": score,
        "dca_safe": dca_safe,
        "dca_validation": {
            "dca_safe": dca_safe,
            "checks": {
                "confluence": score >= 10,
                "qqe_aligned": True,
                "bb_not_squeezing": True,
                "valid_zone": True,
                "bmsb_above": True,
            },
        },
    }


def _add_recommendation(**overrides: object) -> dict:
    rec = {
        "recommendation": "ADD",
        "reason": "Price in OTE zone + QQE aligned. Deploy 20%.",
        "confidence": "HIGH",
        "simulated_add_size": 500.0,
    }
    rec.update(overrides)
    return rec


async def test_add_with_all_gates_passing_persists_would_allow_audit(session: AsyncSession) -> None:
    from backend.services.dca_shadow_service import evaluate_shadow_decision

    decision = await evaluate_shadow_decision(
        session=session,
        user_id=1,
        exchange="mexc",
        symbol="BTCUSDT",
        recommendation=_add_recommendation(),
        scan=_scan(),
        portfolio_value=10_000.0,
        current_dca_exposure=1_000.0,
        exposure_cap_pct=0.25,
        now=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
    )

    assert decision["final_outcome"] == "would_allow"
    assert decision["original_recommendation"] == "ADD"
    assert decision["blocked_gates"] == []
    assert "would be allowed" in decision["final_reason"]
    assert all(gate["passed"] for gate in decision["gate_breakdown"])
    assert decision["assumption_set"]["max_add_size_pct_portfolio"] == 0.10

    rows = (await session.execute(select(FakeDcaShadowDecisionHistory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].final_outcome == "would_allow"
    assert rows[0].original_recommendation == "ADD"
    assert rows[0].blocked_gates == []
    assert rows[0].gate_breakdown == decision["gate_breakdown"]
    assert rows[0].assumption_set == decision["assumption_set"]
    assert rows[0].final_reason == decision["final_reason"]


async def test_add_blocks_visible_safety_gates_with_human_readable_reason(session: AsyncSession) -> None:
    from backend.services.dca_shadow_service import evaluate_shadow_decision

    session.add(FakeDcaShadowGlobalKillSwitch(active=True, reason="maintenance"))
    session.add(FakeDcaShadowUserKillSwitch(user_id=1, active=True, reason="user paused DCA"))
    session.add(
        FakeDcaShadowSymbolKillSwitch(
            user_id=1,
            exchange="mexc",
            symbol="BTCUSDT",
            active=True,
            reason="symbol paused",
        )
    )
    base_now = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        session.add(
            FakeDcaShadowDecisionHistory(
                user_id=1,
                timestamp=(base_now - timedelta(minutes=5 + i)).replace(tzinfo=None),
                exchange="mexc",
                symbol="ETHUSDT",
                original_recommendation="ADD",
                final_outcome="would_allow",
                gate_breakdown=[],
                blocked_gates=[],
                assumption_set={},
                final_reason="prior allowed ADD",
            )
        )
    session.add(
        FakeDcaShadowDecisionHistory(
            user_id=1,
            timestamp=(base_now - timedelta(hours=2)).replace(tzinfo=None),
            exchange="mexc",
            symbol="BTCUSDT",
            original_recommendation="CLOSE",
            final_outcome="would_close",
            gate_breakdown=[],
            blocked_gates=[],
            assumption_set={},
            final_reason="prior close",
        )
    )
    await session.flush()

    decision = await evaluate_shadow_decision(
        session=session,
        user_id=1,
        exchange="mexc",
        symbol="BTCUSDT",
        recommendation=_add_recommendation(simulated_add_size=1_500.0),
        scan=_scan(score=8.0, dca_safe=False),
        portfolio_value=10_000.0,
        current_dca_exposure=2_400.0,
        exposure_cap_pct=0.25,
        now=base_now,
    )

    assert decision["final_outcome"] == "would_block"
    assert set(decision["blocked_gates"]) == {
        "dca_safe",
        "confluence_score",
        "global_kill_switch",
        "user_kill_switch",
        "symbol_kill_switch",
        "hourly_add_limit",
        "close_cooldown_24h",
        "add_size_pct_portfolio",
        "exposure_cap",
    }
    assert "blocked" in decision["final_reason"].lower()
    assert "DCA SAFE" in decision["final_reason"]
    assert any(gate["name"] == "daily_add_limit" and gate["passed"] for gate in decision["gate_breakdown"])

    audit = (await session.execute(select(FakeDcaShadowDecisionHistory))).scalars().all()[-1]
    assert audit.final_outcome == "would_block"
    assert audit.blocked_gates == decision["blocked_gates"]


async def test_kill_switches_do_not_downgrade_reduce_or_emergency_close(session: AsyncSession) -> None:
    from backend.services.dca_shadow_service import evaluate_shadow_decision

    session.add(FakeDcaShadowGlobalKillSwitch(active=True, reason="maintenance"))
    session.add(FakeDcaShadowUserKillSwitch(user_id=1, active=True, reason="paused"))
    session.add(FakeDcaShadowSymbolKillSwitch(user_id=1, exchange="mexc", symbol="BTCUSDT", active=True))
    await session.flush()

    close_decision = await evaluate_shadow_decision(
        session=session,
        user_id=1,
        exchange="mexc",
        symbol="BTCUSDT",
        recommendation={
            "recommendation": "CLOSE",
            "reason": "Mark price only 1.3% from liquidation. Exit immediately.",
            "confidence": "CRITICAL",
        },
        scan=_scan(score=4.0, dca_safe=False),
        portfolio_value=10_000.0,
        current_dca_exposure=3_000.0,
    )
    reduce_decision = await evaluate_shadow_decision(
        session=session,
        user_id=1,
        exchange="mexc",
        symbol="BTCUSDT",
        recommendation={"recommendation": "REDUCE", "reason": "Position up 120%. Withdraw initial capital."},
        scan=_scan(score=4.0, dca_safe=False),
        portfolio_value=10_000.0,
        current_dca_exposure=3_000.0,
    )

    assert close_decision["final_outcome"] == "would_close"
    assert "liquidation" in close_decision["final_reason"].lower()
    assert reduce_decision["final_outcome"] == "would_reduce"
    assert all(gate["passed"] for gate in close_decision["gate_breakdown"])
    assert all(gate["passed"] for gate in reduce_decision["gate_breakdown"])


async def test_no_action_for_hold_and_no_exchange_order_placement_paths_are_called(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.services.exchange_service as exchange_service
    from backend.services.dca_shadow_service import evaluate_shadow_decision

    called: list[str] = []

    async def forbidden_async(*args: object, **kwargs: object) -> None:
        called.append("get_exchange")
        raise AssertionError("shadow mode must not fetch live exchange placement clients")

    def forbidden_sync(*args: object, **kwargs: object) -> None:
        called.append("create_exchange_instance")
        raise AssertionError("shadow mode must not create exchange clients")

    monkeypatch.setattr(exchange_service, "get_exchange", forbidden_async)
    monkeypatch.setattr(exchange_service, "create_exchange_instance", forbidden_sync)

    decision = await evaluate_shadow_decision(
        session=session,
        user_id=1,
        exchange="mexc",
        symbol="BTCUSDT",
        recommendation={"recommendation": "HOLD", "reason": "Wait for pullback."},
        scan=_scan(),
        portfolio_value=10_000.0,
        current_dca_exposure=1_000.0,
    )

    assert decision["final_outcome"] == "no_action"
    assert called == []
    audit = (await session.execute(select(FakeDcaShadowDecisionHistory))).scalar_one()
    assert audit.final_outcome == "no_action"
