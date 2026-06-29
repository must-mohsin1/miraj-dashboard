"""FastAPI application entry-point."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from backend.auth import get_current_user
from backend.database import Base, get_engine
from backend.routes import auth_router, macro_router, scan_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (idempotent)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Crypto Analysis API",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Routers ─────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(macro_router)
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
