"""Tests for the DCA validation API route.

Run with::

    JWT_SECRET_KEY=test-key-not-for-production python -m pytest backend/tests/test_dca_validation_api.py -q
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from typing import Any, AsyncGenerator, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if "JWT_SECRET_KEY" not in os.environ:
    os.environ["JWT_SECRET_KEY"] = "test-key-not-for-production"

from backend.auth import create_access_token, hash_password
from backend.database import Base, set_db_path
from backend.models import Analysis, PortfolioPosition, User
from backend.routes import dca_validation, portfolio


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="dca_validation_api_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
async def app(tmp_db_path: str) -> AsyncGenerator[FastAPI, None]:
    from backend import database

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    set_db_path(tmp_db_path)

    app = FastAPI()
    app.include_router(dca_validation.router)
    app.include_router(portfolio.router)

    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield app

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _create_user(username: str, email: str) -> tuple[User, str]:
    from backend.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password("testpass123"),
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        token = create_access_token(data={"sub": str(user.id)})
        await session.commit()
    return user, token


async def _insert_position_and_scan(
    *,
    user_id: int,
    exchange: str,
    symbol: str,
    created_at: datetime,
    rsi: float,
    price: float,
) -> None:
    from backend.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        assert await session.get(User, user_id) is not None
        session.add(
            PortfolioPosition(
                user_id=user_id,
                exchange=exchange,
                symbol=symbol,
                side="LONG",
                size=1.0,
                entry_price=100.0,
                mark_price=price,
                pnl=0.0,
                pnl_percent=0.0,
                leverage=1.0,
                margin=100.0,
            )
        )
        session.add(
            Analysis(
                user_id=user_id,
                pair=symbol,
                analysis_type="scheduled_scan",
                parameters=json.dumps({"exchange": exchange}),
                result=json.dumps(
                    {
                        "trade_plan": {"direction": "LONG", "reasoning": "test scan"},
                        "rsi": rsi,
                        "mark_price": price,
                        "confidence": 12,
                    }
                ),
                score=12.0,
                created_at=created_at,
            )
        )
        await session.commit()


class TestDcaValidationApi:
    async def test_authenticated_validation_returns_typed_available_response_scoped_to_user(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user, token = await _create_user("dcauser", "dca@example.com")
        seen: dict[str, Any] = {}

        async def fake_reconstruct(session, user_id, exchange, symbol=None, start_date=None, end_date=None):
            seen["reconstruction"] = {
                "user_id": user_id,
                "exchange": exchange,
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
            }
            return {
                "exchange": exchange,
                "method": "scan-to-scan",
                "method_description": "scan-history reconstruction; not candle-level historical replay",
                "fill_assumptions": {"fee_percent": 0.04, "slippage_percent": 0.05},
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "metrics_available",
                        "required_minimum_scans": 2,
                        "scan_count": 3,
                        "first_scan_at": "2026-07-01T00:00:00",
                        "last_scan_at": "2026-07-03T00:00:00",
                        "max_scan_gap_seconds": 86400,
                        "events": [{"recommendation": "ADD", "participates_in_metrics": True}],
                        "skipped_scans": [],
                    }
                ],
            }

        def fake_metrics(reconstruction, *, split_ratio):
            seen["metrics"] = {"reconstruction": reconstruction, "split_ratio": split_ratio}
            return {
                "exchange": reconstruction["exchange"],
                "split_ratio": split_ratio,
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "metrics_available",
                        "metrics": {"win_rate": {"value": 100.0, "reason": None}},
                    }
                ],
                "portfolio": {"metrics": {"win_rate": {"value": 100.0, "reason": None}}},
            }

        async def fake_shadow_history(session, user_id, exchange, symbol=None, outcome=None, start=None, end=None, limit=50):
            seen["shadow"] = {
                "user_id": user_id,
                "exchange": exchange,
                "symbol": symbol,
                "outcome": outcome,
                "start": start,
                "end": end,
                "limit": limit,
            }
            return [{"symbol": symbol, "final_outcome": "would_block", "blocked_gates": ["dca_safe"]}]

        monkeypatch.setattr(dca_validation, "reconstruct_scan_history", fake_reconstruct)
        monkeypatch.setattr(dca_validation, "compute_dca_validation_metrics", fake_metrics)
        monkeypatch.setattr(dca_validation, "list_shadow_history", fake_shadow_history)

        resp = await client.get(
            "/api/v1/dca-validation/binance?symbol=BTCUSDT&outcome=would_block&limit=7&start_date=2026-07-01T00:00:00&end_date=2026-07-04T00:00:00&split_ratio=0.6",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "metrics_available"
        assert body["exchange"] == "binance"
        assert body["request"]["symbol"] == "BTCUSDT"
        assert body["request"]["split_ratio"] == 0.6
        assert body["reconstruction"]["symbols"][0]["status"] == "metrics_available"
        assert body["metrics"]["symbols"][0]["symbol"] == "BTCUSDT"
        assert body["shadow_history"][0]["final_outcome"] == "would_block"
        assert body["disclaimer"] == "These are reconstructed and shadow-mode results, not realized trading performance or financial advice."
        assert seen["reconstruction"] == {
            "user_id": user.id,
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "start_date": datetime(2026, 7, 1, 0, 0),
            "end_date": datetime(2026, 7, 4, 0, 0),
        }
        assert seen["shadow"]["user_id"] == user.id
        assert seen["shadow"]["exchange"] == "binance"
        assert seen["shadow"]["symbol"] == "BTCUSDT"
        assert seen["shadow"]["outcome"] == "would_block"
        assert seen["shadow"]["limit"] == 7

    async def test_route_uses_real_reconstruction_signature_and_filters_scan_dates(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user, token = await _create_user("realrecon", "realrecon@example.com")
        await _insert_position_and_scan(
            user_id=cast(int, user.id),
            exchange="binance",
            symbol="BTCUSDT",
            created_at=datetime(2026, 6, 30, 0, 0),
            rsi=40,
            price=100,
        )
        await _insert_position_and_scan(
            user_id=cast(int, user.id),
            exchange="binance",
            symbol="BTCUSDT",
            created_at=datetime(2026, 7, 2, 0, 0),
            rsi=32,
            price=95,
        )

        monkeypatch.setattr(dca_validation, "compute_dca_validation_metrics", lambda reconstruction, *, split_ratio: {"symbols": [], "portfolio": {}})
        monkeypatch.setattr(dca_validation, "list_shadow_history", lambda **kwargs: [])

        resp = await client.get(
            "/api/v1/dca-validation/binance?symbol=BTCUSDT&start_date=2026-07-01T00:00:00&end_date=2026-07-03T00:00:00",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        symbol = resp.json()["reconstruction"]["symbols"][0]
        assert symbol["symbol"] == "BTCUSDT"
        assert symbol["scan_count"] == 1
        assert symbol["first_scan_at"] == "2026-07-02T00:00:00"
        assert symbol["last_scan_at"] == "2026-07-02T00:00:00"

    async def test_insufficient_history_is_first_class_typed_state(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _user, token = await _create_user("sparse", "sparse@example.com")

        async def fake_reconstruct(session, user_id, exchange, symbol=None, start_date=None, end_date=None):
            return {
                "exchange": exchange,
                "method": "scan-to-scan",
                "method_description": "scan-history reconstruction; not candle-level historical replay",
                "fill_assumptions": {},
                "symbols": [
                    {
                        "symbol": "ETHUSDT",
                        "status": "insufficient_history",
                        "required_minimum_scans": 2,
                        "scan_count": 1,
                        "first_scan_at": "2026-07-01T00:00:00",
                        "last_scan_at": "2026-07-01T00:00:00",
                        "max_scan_gap_seconds": None,
                        "events": [],
                        "skipped_scans": [],
                    }
                ],
            }

        monkeypatch.setattr(dca_validation, "reconstruct_scan_history", fake_reconstruct)
        monkeypatch.setattr(dca_validation, "compute_dca_validation_metrics", lambda reconstruction, *, split_ratio: {"symbols": [], "portfolio": {}})
        monkeypatch.setattr(dca_validation, "list_shadow_history", lambda **kwargs: [])

        resp = await client.get(
            "/api/v1/dca-validation/binance?symbol=ETHUSDT",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "insufficient_history"
        assert body["reconstruction"]["symbols"][0]["required_minimum_scans"] == 2
        assert body["metrics"] is None
        assert body["validation_errors"] == []

    async def test_invalid_split_ratio_returns_4xx_human_readable_error(
        self,
        client: AsyncClient,
    ) -> None:
        _user, token = await _create_user("badsplit", "badsplit@example.com")

        resp = await client.get(
            "/api/v1/dca-validation/binance?split_ratio=1.5",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 422
        assert "split_ratio must be greater than 0 and less than 1" in resp.json()["detail"]

    async def test_reconstruction_timeout_returns_non_blocking_last_completed_state(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _user, token = await _create_user("slow", "slow@example.com")

        async def fast_reconstruct(session, user_id, exchange, symbol=None, start_date=None, end_date=None):
            return {"exchange": exchange, "symbols": []}

        async def slow_reconstruct(session, user_id, exchange, symbol=None, start_date=None, end_date=None):
            await asyncio.sleep(0.05)
            return {"exchange": exchange, "symbols": []}

        monkeypatch.setattr(dca_validation, "reconstruct_scan_history", fast_reconstruct)
        monkeypatch.setattr(dca_validation, "compute_dca_validation_metrics", lambda reconstruction, *, split_ratio: {"symbols": [], "portfolio": {}})
        monkeypatch.setattr(dca_validation, "list_shadow_history", lambda **kwargs: [])

        completed = await client.get(
            "/api/v1/dca-validation/binance?symbol=SOLUSDT",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert completed.status_code == 200

        monkeypatch.setattr(dca_validation, "reconstruct_scan_history", slow_reconstruct)
        timed_out = await client.get(
            "/api/v1/dca-validation/binance?symbol=SOLUSDT&timeout_ms=1",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert timed_out.status_code == 200
        body = timed_out.json()
        assert body["state"] == "reconstructing"
        assert body["last_completed"] is not None
        assert body["reconstruction"] == completed.json()["reconstruction"]

    async def test_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/dca-validation/binance")

        assert resp.status_code == 401

    async def test_existing_portfolio_dca_endpoint_remains_unchanged(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _user, token = await _create_user("compat", "compat@example.com")

        async def no_positions(session, user_id, exchange):
            return []

        monkeypatch.setattr(portfolio, "_require_supported_exchange", lambda exchange: exchange)
        monkeypatch.setattr(portfolio, "_load_positions", no_positions)

        resp = await client.get(
            "/api/v1/portfolio/binance/dca",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "exchange": "binance",
            "total_positions": 0,
            "add_count": 0,
            "reduce_count": 0,
            "close_count": 0,
            "hold_count": 0,
            "positions": [],
        }
