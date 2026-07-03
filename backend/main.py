"""FastAPI application entry-point."""

import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI

from backend.auth import get_current_user
from backend.database import Base, get_engine
# Import portfolio models so Base.metadata.create_all() creates their tables.
from backend.models import (  # noqa: F401 — imported for side effect (table registration)
    ExchangeKey,
    OrderHistory,
    PortfolioBalance,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioTrade,
    PositionHistory,
)
from backend.routes import (
    auth_router,
    charts_router,
    history_router,
    macro_router,
    portfolio_router,
    price_alerts_router,
    results_router,
    scan_router,
    settings_router,
    stream_router,
    watchlist_router,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup, auto-migrate new columns, and start the scheduler."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ── Auto-migrate: add missing columns to existing tables ──────────
    # SQLite doesn't add new columns automatically via create_all.
    # This block checks each known table and adds columns if missing.
    import sqlite3 as _sqlite3
    import os as _os
    _db_path = _os.environ.get("DATABASE_URL", "crypto_analysis.db")
    if _db_path.startswith("sqlite"):
        _db_path = _db_path.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    try:
        _conn = _sqlite3.connect(_db_path)
        _cursor = _conn.cursor()

        # Check portfolio_balances for usd_value column
        _cursor.execute("PRAGMA table_info(portfolio_balances)")
        _cols = [row[1] for row in _cursor.fetchall()]
        if _cols and "usd_value" not in _cols:
            _cursor.execute("ALTER TABLE portfolio_balances ADD COLUMN usd_value REAL")
            logger.info("Migrated portfolio_balances: added usd_value column")

        _conn.commit()
        _conn.close()
    except Exception as _e:
        logger.warning("Auto-migration check failed (non-critical): %s", _e)

    # ── Validate alert / sync configs at startup ────────────────────
    import os as _os

    _telegram_token = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
    _telegram_chat = _os.environ.get("TELEGRAM_CHAT_ID", "")
    if _telegram_token and not _telegram_chat:
        logger.warning(
            "TELEGRAM_BOT_TOKEN is set but TELEGRAM_CHAT_ID is not — "
            "alerts will not be delivered. Set TELEGRAM_CHAT_ID in .env"
        )
    if _telegram_chat and not _telegram_token:
        logger.warning(
            "TELEGRAM_CHAT_ID is set but TELEGRAM_BOT_TOKEN is not — "
            "alerts will not be delivered. Set TELEGRAM_BOT_TOKEN in .env"
        )

    _discord_url = _os.environ.get("DISCORD_WEBHOOK_URL", "")
    if _discord_url and not _discord_url.startswith("https://discord.com/api/webhooks/"):
        logger.warning(
            "DISCORD_WEBHOOK_URL does not look like a valid Discord webhook URL "
            "(must start with https://discord.com/api/webhooks/)"
        )

    _vault_path = _os.environ.get("OBSIDIAN_VAULT_PATH", "")
    if _vault_path and not _os.path.isdir(_vault_path):
        logger.warning(
            "OBSIDIAN_VAULT_PATH=%s does not exist or is not a directory — "
            "Obsidian vault sync will fail. Update the path in .env",
            _vault_path,
        )

    # ── SMTP email config check ─────────────────────────────────────
    _smtp_host = _os.environ.get("SMTP_HOST", "")
    _smtp_user = _os.environ.get("SMTP_USER", "")
    _smtp_pass = _os.environ.get("SMTP_PASSWORD", "")
    if _smtp_host and (_smtp_user and not _smtp_pass):
        logger.warning(
            "SMTP_HOST and SMTP_USER are set but SMTP_PASSWORD is not — "
            "email alerts will not be delivered. Set SMTP_PASSWORD in .env"
        )
    if _smtp_host and (_smtp_pass and not _smtp_user):
        logger.warning(
            "SMTP_HOST and SMTP_PASSWORD are set but SMTP_USER is not — "
            "email alerts will not be delivered. Set SMTP_USER in .env"
        )

    # ── Start APScheduler ────────────────────────────────────────────
    from backend.scheduler import setup_scheduler, start_scheduler

    setup_scheduler(app)
    # Start the scheduler as a background task so FastAPI startup isn't
    # blocked and the scheduler runs for the lifetime of the app.
    asyncio.create_task(_start_scheduler_task())

    yield

    # ── Stop APScheduler ─────────────────────────────────────────────
    from backend.scheduler import stop_scheduler

    stop_scheduler()


async def _start_scheduler_task() -> None:
    """Background task wrapper that starts APScheduler on app startup.

    Wrapped in an exception boundary so a scheduler failure never crashes
    the FastAPI server process — it logs and exits the task only.
    """
    try:
        from backend.scheduler import start_scheduler

        start_scheduler()
        logger.info("APScheduler started as background task")
    except Exception as exc:
        logger.exception("Failed to start APScheduler: %s", exc)


app = FastAPI(
    title="Crypto Analysis API",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Routers ─────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(macro_router)
app.include_router(price_alerts_router)
app.include_router(results_router)
app.include_router(settings_router)
app.include_router(stream_router)
app.include_router(watchlist_router)
app.include_router(scan_router)
app.include_router(portfolio_router)
app.include_router(charts_router)


# ── Simple health / protected check ─────────────────────────────────────────


@app.get("/api/v1/protected")
async def protected_endpoint(
    current_user=Depends(get_current_user),
):
    """Return a simple success message if the caller is authenticated."""
    return {
        "message": "You are authenticated",
        "user": current_user.username,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
