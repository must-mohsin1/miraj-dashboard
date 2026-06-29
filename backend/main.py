"""FastAPI application entry-point."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from backend.auth import get_current_user
from backend.database import Base, get_engine
from backend.routes import (
    auth_router,
    history_router,
    macro_router,
    results_router,
    scan_router,
    watchlist_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (idempotent) and start the scheduler."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
app.include_router(results_router)
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
