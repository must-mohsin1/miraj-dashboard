"""Startup scheduler safety tests."""

from __future__ import annotations

import os
import tempfile
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi import FastAPI

# Force JWT secret (required by backend.auth at import time)
os.environ.setdefault("JWT_SECRET_KEY", "test-key-not-for-production")

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def tmp_db_path() -> Generator[str, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="scheduler_startup_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


async def test_lifespan_skips_apscheduler_when_disabled_for_local_fixture_qa(
    tmp_db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fixture QA can opt out of startup jobs that would hit exchange APIs."""
    from backend import database
    from backend.main import lifespan

    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    database.set_db_path(tmp_db_path)
    monkeypatch.setenv("MIRAJ_DISABLE_APSCHEDULER", "1")

    with patch(
        "backend.scheduler.setup_scheduler",
        side_effect=AssertionError("scheduler setup must not run"),
    ), patch(
        "backend.scheduler.start_scheduler",
        side_effect=AssertionError("scheduler start must not run"),
    ), patch(
        "backend.scheduler.stop_scheduler",
        side_effect=AssertionError("scheduler stop must not run"),
    ):
        async with lifespan(FastAPI()):
            pass
