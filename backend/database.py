"""Async SQLAlchemy engine and session factory backed by aiosqlite (SQLite)."""

import os
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_DB_PATH: Optional[str] = None
_engine = None
_session_factory = None


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
    url = f"sqlite+aiosqlite:///{db_path}"
    return create_async_engine(url, echo=False)


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
