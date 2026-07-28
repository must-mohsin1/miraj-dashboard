"""Focused tests for application SQLite connection configuration."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from backend import database

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def reset_database_module():
    original_path = database._DB_PATH
    original_engine = database._engine
    original_factory = database._session_factory
    database._DB_PATH = None
    database._engine = None
    database._session_factory = None
    try:
        yield
    finally:
        engine = database._engine
        if engine is not None:
            await engine.dispose()
        database._DB_PATH = original_path
        database._engine = original_engine
        database._session_factory = original_factory


def _cleanup_sqlite_sidecars(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            db_path.with_name(db_path.name + suffix).unlink()
        except FileNotFoundError:
            pass


async def _pragma_value(connection, pragma_name: str):
    return (await connection.execute(text(f"PRAGMA {pragma_name}"))).scalar_one()


async def _assert_file_backed_sqlite_pragmas(connection) -> None:
    assert await _pragma_value(connection, "busy_timeout") == 30000
    assert str(await _pragma_value(connection, "journal_mode")).lower() == "wal"
    assert await _pragma_value(connection, "synchronous") == 1
    assert await _pragma_value(connection, "foreign_keys") == 1


async def test_file_backed_connections_report_required_pragmas(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    database.set_db_path(str(db_path))

    engine = database.get_engine()
    async with engine.connect() as first:
        await _assert_file_backed_sqlite_pragmas(first)
    async with engine.connect() as second:
        await _assert_file_backed_sqlite_pragmas(second)

    await engine.dispose()
    _cleanup_sqlite_sidecars(db_path)


async def test_sqlite_url_style_path_is_preserved_and_configured(tmp_path: Path) -> None:
    db_path = tmp_path / "url-style.db"
    database.set_db_path(f"sqlite:///{db_path}")

    engine = database.get_engine()
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
        await _assert_file_backed_sqlite_pragmas(connection)

    await engine.dispose()
    assert db_path.exists()
    _cleanup_sqlite_sidecars(db_path)


async def test_engine_reset_reapplies_required_pragmas(tmp_path: Path) -> None:
    first_path = tmp_path / "first.db"
    database.set_db_path(str(first_path))
    first_engine = database.get_engine()
    async with first_engine.connect() as connection:
        await _assert_file_backed_sqlite_pragmas(connection)
    await first_engine.dispose()
    _cleanup_sqlite_sidecars(first_path)

    second_path = tmp_path / "second.db"
    database.set_db_path(str(second_path))
    second_engine = database.get_engine()
    async with database.get_session_factory()() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
        connection = await session.connection()
        await _assert_file_backed_sqlite_pragmas(connection)

    await second_engine.dispose()
    _cleanup_sqlite_sidecars(second_path)


async def test_in_memory_sqlite_is_not_forced_to_wal() -> None:
    database.set_db_path(":memory:")

    engine = database.get_engine()
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
        journal_mode = str(await _pragma_value(connection, "journal_mode")).lower()
        assert journal_mode != "wal"
        assert await _pragma_value(connection, "foreign_keys") == 1

    await engine.dispose()


async def test_second_writer_waits_for_lock_release_on_file_backed_database(tmp_path: Path) -> None:
    db_path = tmp_path / "contention.db"
    database.set_db_path(str(db_path))

    engine = database.get_engine()
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE contention (id INTEGER PRIMARY KEY, value TEXT)"))

    async with engine.connect() as first, engine.connect() as second:
        first_transaction = await first.begin()
        await first.execute(text("INSERT INTO contention (value) VALUES ('first')"))

        async def write_with_second_connection():
            started = time.monotonic()
            try:
                async with second.begin():
                    await second.execute(text("INSERT INTO contention (value) VALUES ('second')"))
            except OperationalError as exc:
                return "locked", time.monotonic() - started, str(exc)
            return "success", time.monotonic() - started, ""

        write_task = asyncio.create_task(write_with_second_connection())
        await asyncio.sleep(0.2)
        await first_transaction.commit()
        outcome, elapsed, error = await asyncio.wait_for(write_task, timeout=5)

    async with engine.connect() as connection:
        row_count = (await connection.execute(text("SELECT COUNT(*) FROM contention"))).scalar_one()

    await engine.dispose()
    _cleanup_sqlite_sidecars(db_path)

    if outcome == "success":
        assert row_count == 2
        assert elapsed >= 0.1
        assert elapsed < 5
    else:
        assert outcome == "locked"
        assert "database is locked" in error.lower()
        assert elapsed < 5
