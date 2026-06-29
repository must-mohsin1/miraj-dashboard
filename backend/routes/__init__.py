"""API route registration."""
from backend.routes.auth import router as auth_router
from backend.routes.macro import router as macro_router
from backend.routes.scan import router as scan_router

__all__ = ["auth_router", "macro_router", "scan_router"]
