"""API route registration."""
from backend.routes.auth import router as auth_router
from backend.routes.history import router as history_router
from backend.routes.macro import router as macro_router
from backend.routes.results import router as results_router
from backend.routes.scan import router as scan_router
from backend.routes.watchlist import router as watchlist_router

__all__ = ["auth_router", "history_router", "macro_router", "results_router", "scan_router", "watchlist_router"]