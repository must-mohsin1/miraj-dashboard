"""Route tests for the read-only desktop position-intelligence API."""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Iterator, cast

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
from backend.routes import desktop

pytestmark = pytest.mark.anyio


def anyio_backend() -> str:
    return "asyncio"




@pytest.fixture
def tmp_db_path() -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="desktop_position_route_test_")
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

    test_app = FastAPI()
    test_app.include_router(desktop.router)

    engine = database.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield test_app

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _create_user(username: str = "desktopuser", email: str = "desktop@example.com") -> tuple[User, str]:
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


async def _insert_cached_desktop_inputs(user_id: int) -> None:
    from backend.database import get_session_factory

    factory = get_session_factory()
    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    async with factory() as session:
        session.add(
            PortfolioPosition(
                user_id=user_id,
                exchange="mexc",
                symbol="BTCUSDT",
                side="LONG",
                size=3.0,
                entry_price=100.0,
                mark_price=105.0,
                pnl=15.0,
                pnl_percent=50.0,
                leverage=5.0,
                liquidation_price=80.0,
                margin=30.0,
                contract_size=0.5,
                updated_at=now,
            )
        )
        session.add(
            Analysis(
                user_id=user_id,
                pair="BTCUSDT",
                analysis_type="scheduled_scan",
                parameters=json.dumps({"exchange": "mexc"}),
                result=json.dumps(
                    {
                        "exchange": "mexc",
                        "structure": {
                            "weekly": {
                                "label": "HL",
                                "swings": [
                                    {"type": "low", "price": 80.0, "index": 3},
                                    {"type": "high", "price": 128.0, "index": 4},
                                ],
                            },
                            "daily": {
                                "label": "HH",
                                "swings": [
                                    {"type": "low", "price": 101.0, "index": 9},
                                    {"type": "high", "price": 111.0, "index": 10},
                                ],
                            },
                            "4h": {
                                "label": "HL",
                                "swings": [
                                    {"type": "low", "price": 102.0, "index": 11},
                                    {"type": "high", "price": 109.0, "index": 12},
                                ],
                            },
                            "1h": {
                                "label": "HL",
                                "swings": [
                                    {"type": "low", "price": 103.0, "index": 21},
                                    {"type": "high", "price": 107.0, "index": 22},
                                ],
                            },
                        },
                        "dca": {"recommendation": "HOLD", "reason": "Cached DCA hold"},
                        "position_alerts": {
                            "max_severity": "WARNING",
                            "alerts": [{"severity": "WARNING", "type": "STRUCTURE", "message": "cached warning"}],
                        },
                    }
                ),
                score=21.0,
                created_at=now,
            )
        )
        await session.commit()


def _app(authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(desktop.router)
    if authenticated:
        async def current_user_override() -> SimpleNamespace:
            return SimpleNamespace(id=42, username="route-test-user")

        async def session_override() -> object:
            return object()

        app.dependency_overrides[desktop.get_current_user] = current_user_override
        app.dependency_overrides[desktop.get_session] = session_override
    return app


def _service_payload(symbol: str = "BTCUSDT") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "exchange": "mexc",
        "selection_reason": "user_selected",
        "generated_at": "2026-07-15T10:30:00Z",
        "source": {
            "portfolio_last_refreshed": "2026-07-15T10:29:30Z",
            "mark_price_source": "cached_position",
            "mark_price_last_refreshed": "2026-07-15T10:29:30Z",
            "pnl_age_seconds": 30,
            "stale_status": "fresh",
            "refresh_executed": False,
        },
        "position": {
            "symbol": symbol,
            "exchange": "mexc",
            "side": "LONG",
            "size_contracts": 3.0,
            "contract_size": 0.5,
            "entry_price": 100.0,
            "mark_price": 110.0,
            "pnl": 15.0,
            "pnl_percent": 50.0,
            "pnl_formula": "computed_contracts_contract_size",
            "margin": 30.0,
            "leverage": 5.0,
            "liquidation_price": 75.0,
            "liquidation_distance_pct": 31.8181818,
            "htf_sr": {"timeframes": ["Daily", "Weekly"], "support": None, "resistance": None, "structure_label": "unknown", "confidence": "UNAVAILABLE"},
            "ltf_sr": {"timeframes": ["1H", "4H"], "support": None, "resistance": None, "structure_label": "unknown", "confidence": "UNAVAILABLE"},
            "advisory": {"action": "WAIT", "severity": "INFO", "reason": "Advisory: Open Miraj before changing the position", "source": "fallback", "action_items_count": 0},
            "dashboard_deeplink": "/portfolio?exchange=mexc&symbol=BTCUSDT",
        },
        "privacy": {"hide_amounts_available": True, "redaction_supported": True},
        "errors": [],
    }


async def test_position_intelligence_requires_authenticated_miraj_user() -> None:
    app = _app(authenticated=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/desktop/position-intelligence?exchange=mexc")

    assert response.status_code == 401
    assert "position" not in response.text.lower()
    assert "pnl" not in response.text.lower()


async def test_position_intelligence_delegates_authenticated_mexc_request_to_desktop_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    async def fake_positions(session: object, user_id: int, exchange: str) -> list[dict[str, Any]]:
        calls["positions"] = {"session": session, "user_id": user_id, "exchange": exchange}
        return [{"symbol": "BTCUSDT", "side": "LONG", "size": 3.0}]

    def fake_builder(**kwargs: Any) -> dict[str, Any]:
        calls["builder"] = kwargs
        return _service_payload(symbol=kwargs["selected_symbol"])

    async def fake_source_times(session: object, user_id: int, exchange: str) -> dict[str, Any]:
        calls["source_times"] = {"user_id": user_id, "exchange": exchange}
        return {}

    async def fake_latest_scans(session: object, user_id: int, exchange: str, symbols: set[str]) -> dict[str, Any]:
        calls["latest_scans"] = {"user_id": user_id, "exchange": exchange, "symbols": symbols}
        return {
            "BTCUSDT": {
                "dca": {"recommendation": "HOLD"},
                "position_alerts": {"max_severity": "WARNING", "alerts": []},
            }
        }

    monkeypatch.setattr(desktop, "_load_cached_positions", fake_positions)
    monkeypatch.setattr(desktop, "_load_source_times", fake_source_times)
    monkeypatch.setattr(desktop, "_load_latest_scans", fake_latest_scans)
    monkeypatch.setattr(desktop, "build_desktop_position_intelligence", fake_builder)

    app = _app(authenticated=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/desktop/position-intelligence?exchange=mexc&symbol=BTCUSDT")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["exchange"] == "mexc"
    assert body["position"]["symbol"] == "BTCUSDT"
    assert calls["positions"]["user_id"] == 42
    assert calls["positions"]["exchange"] == "mexc"
    assert calls["source_times"] == {"user_id": 42, "exchange": "mexc"}
    assert calls["latest_scans"] == {"user_id": 42, "exchange": "mexc", "symbols": {"BTCUSDT"}}
    assert calls["builder"]["positions"] == [{"symbol": "BTCUSDT", "side": "LONG", "size": 3.0}]
    assert calls["builder"]["selected_symbol"] == "BTCUSDT"
    assert calls["builder"]["exchange"] == "mexc"
    assert calls["builder"]["scans_by_symbol"] == {
        "BTCUSDT": {
            "dca": {"recommendation": "HOLD"},
            "position_alerts": {"max_severity": "WARNING", "alerts": []},
        }
    }
    assert calls["builder"]["dca_recommendations_by_symbol"] == {"BTCUSDT": {"recommendation": "HOLD"}}
    assert calls["builder"]["position_alerts_by_symbol"] == {"BTCUSDT": {"max_severity": "WARNING", "alerts": []}}


async def test_position_intelligence_rejects_non_mexc_exchange_without_private_data() -> None:
    app = _app(authenticated=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/desktop/position-intelligence?exchange=binance")

    assert response.status_code == 404
    assert response.headers["x-error-code"] == "unsupported_exchange"
    assert response.json()["detail"] == "Unsupported desktop exchange"
    assert "position" not in response.text.lower()
    assert "pnl" not in response.text.lower()


async def test_position_intelligence_errors_are_user_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_positions(session: object, user_id: int, exchange: str) -> list[dict[str, Any]]:
        return [{"symbol": "BTCUSDT"}]

    async def fake_source_times(session: object, user_id: int, exchange: str) -> dict[str, Any]:
        return {}

    def failing_builder(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("secret jwt token exchange key raw credential payload")

    monkeypatch.setattr(desktop, "_load_cached_positions", fake_positions)
    monkeypatch.setattr(desktop, "_load_source_times", fake_source_times)
    monkeypatch.setattr(desktop, "build_desktop_position_intelligence", failing_builder)

    app = _app(authenticated=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/desktop/position-intelligence?exchange=mexc")

    assert response.status_code == 502
    assert response.headers["x-error-code"] == "desktop_position_intelligence_unavailable"
    assert response.json()["detail"] == "Unable to build desktop position intelligence"
    lower_body = response.text.lower()
    for forbidden in ("secret", "jwt", "token", "exchange key", "credential", "payload"):
        assert forbidden not in lower_body


async def test_authenticated_route_uses_cached_scan_dca_and_alert_inputs_with_real_builder(client: AsyncClient) -> None:
    user, token = await _create_user("realbuilder", "realbuilder@example.com")
    await _insert_cached_desktop_inputs(cast(int, user.id))

    response = await client.get(
        "/api/v1/desktop/position-intelligence?exchange=mexc&symbol=btcusdt",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["selection_reason"] == "user_selected"
    assert body["source"]["refresh_executed"] is False
    assert body["source"]["mark_price_source"] == "cached_position"

    position = body["position"]
    assert position["symbol"] == "BTCUSDT"
    assert position["htf_sr"]["confidence"] == "HIGH"
    assert position["htf_sr"]["support"] == {
        "price": 101.0,
        "distance_pct": pytest.approx(-3.8095238),
        "method": "smc_swing",
        "timeframe": "Daily",
        "swing_type": "swing_low",
        "swing_index": 9,
    }
    assert position["ltf_sr"]["confidence"] == "HIGH"
    assert position["ltf_sr"]["resistance"] == {
        "price": 107.0,
        "distance_pct": pytest.approx(1.9047619),
        "method": "smc_swing",
        "timeframe": "1H",
        "swing_type": "swing_high",
        "swing_index": 22,
    }
    assert position["advisory"]["action"] == "REDUCE"
    assert position["advisory"]["severity"] == "WARNING"
    assert position["advisory"]["source"] == "combined"
    assert position["advisory"]["action_items_count"] == 1


def test_desktop_route_exposes_only_read_only_position_intelligence_endpoint() -> None:
    paths = {route.path: sorted(route.methods or []) for route in desktop.router.routes}
    assert paths == {"/api/v1/desktop/position-intelligence": ["GET"]}

    source = inspect.getsource(desktop)
    forbidden_side_effects = (
        "fetch_portfolio",
        "get_exchange",
        "create_exchange_instance",
        "validate_exchange_keys",
        "refresh_portfolio",
        "connect_exchange",
        "disconnect_exchange",
        "place_order",
        "create_order",
        "set_leverage",
        "execute_dca",
    )
    for forbidden in forbidden_side_effects:
        assert forbidden not in source
