"""Async SQLAlchemy engine and session factory backed by aiosqlite (SQLite)."""

import os
from typing import Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_DB_PATH: Optional[str] = None
_engine = None
_session_factory = None
_SQLITE_BUSY_TIMEOUT_MS = 30000


class Base(DeclarativeBase):
    pass


def get_db_path() -> str:
    """Return the configured database path, defaulting to ``./crypto_analysis.db``."""
    if _DB_PATH is not None:
        return _DB_PATH
    return os.environ.get("DATABASE_URL", "crypto_analysis.db")


def set_db_path(path: str) -> None:
    """Override the database file path (useful for tests)."""
    global _DB_PATH
    global _engine
    global _session_factory
    _DB_PATH = path
    _engine = None
    _session_factory = None


def _make_engine(db_path: str):
    """Create a new SQLAlchemy async engine for the given SQLite file."""
    url = _sqlite_async_url(db_path)
    engine = create_async_engine(url, echo=False, connect_args={"timeout": 30})
    _configure_sqlite_pragmas(engine, force_wal=not _is_in_memory_sqlite(db_path))
    return engine


def _sqlite_async_url(db_path: str) -> str:
    """Return a sqlite+aiosqlite URL for path-style or sqlite URL configuration."""
    if db_path.startswith("sqlite+aiosqlite://"):
        return db_path
    if db_path.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + db_path.removeprefix("sqlite://")
    return f"sqlite+aiosqlite:///{db_path}"


def _is_in_memory_sqlite(db_path: str) -> bool:
    """Return True when the configured SQLite database is in-memory."""
    return db_path == ":memory:" or ":memory:" in db_path or "mode=memory" in db_path


def _configure_sqlite_pragmas(engine, *, force_wal: bool) -> None:
    """Install per-connection SQLite PRAGMAs for contention and integrity."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
            if force_wal:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def get_engine():
    """Return the singleton engine, creating it if needed."""
    global _engine
    if _engine is None:
        _engine = _make_engine(get_db_path())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory, creating it if needed."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yield an async session per request."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
