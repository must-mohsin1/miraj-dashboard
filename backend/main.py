"""FastAPI application entry-point."""

from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI

from backend.auth import get_current_user
from backend.database import Base, get_engine
from backend.routes import (
    auth_router,
    history_router,
    macro_router,
    price_alerts_router,
    results_router,
    scan_router,
    settings_router,
    watchlist_router,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (idempotent) and start the scheduler."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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

    # ── Start APScheduler ────────────────────────────────────────────
    from backend.scheduler import setup_scheduler, start_scheduler

    setup_scheduler(app)
    start_scheduler()
    yield
    # ── Stop APScheduler ─────────────────────────────────────────────
    from backend.scheduler import stop_scheduler

    stop_scheduler()


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
app.include_router(watchlist_router)
app.include_router(scan_router)


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
