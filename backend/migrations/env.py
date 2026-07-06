"""Alembic environment configuration for async SQLAlchemy + autogenerate.

Uses the same database URL resolution as the app (DATABASE_URL env var
→ sqlite+aiosqlite:///<path>) and imports the project's Base.metadata
for autogenerate support.
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# ── Ensure the project root is on sys.path so `backend.xxx` imports work ──
# env.py lives at backend/migrations/env.py; project root is 2 levels up.
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Project model import for autogenerate ─────────────────────────────
# Import Base so that Base.metadata reflects all models.
# The models themselves register their tables on Base at import time.
from backend.database import Base  # noqa: E402
from backend.models import (       # noqa: E402, F401
    AlertChannel,
    AlertHistory,
    Analysis,
    ExchangeKey,
    OrderHistory,
    PairSetting,
    PortfolioBalance,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioTrade,
    PositionHistory,
    PriceAlert,
    ScanRun,
    TradeJournalEntry,
    User,
    WatchlistPair,
)

target_metadata = Base.metadata

# ── Database URL resolution (same logic as backend.database.get_db_path) ──
def get_db_url() -> str:
    """Return the async SQLAlchemy URL matching the app's resolution."""
    db_path = os.environ.get("DATABASE_URL", "crypto_analysis.db")
    # If env already set to a full URL (e.g. sqlite+aiosqlite:///...), use as-is
    if db_path.startswith("sqlite"):
        return db_path
    return f"sqlite+aiosqlite:///{db_path}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation).

    Requires a sync-compatible URL (strip +aiosqlite driver hint).
    """
    url = get_db_url().replace("+aiosqlite", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using the async engine."""
    url = get_db_url()

    async def do_migrations() -> None:
        connectable = create_async_engine(url)
        try:
            async with connectable.connect() as connection:
                await connection.run_sync(
                    lambda sync_conn: context.configure(
                        connection=sync_conn,
                        target_metadata=target_metadata,
                    )
                )
                async with connection.begin():
                    await connection.run_sync(
                        lambda sync_conn: context.run_migrations()
                    )
        finally:
            await connectable.dispose()

    asyncio.run(do_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
