"""API route registration."""
from backend.routes.auth import router as auth_router
from backend.routes.charts import router as charts_router
from backend.routes.history import router as history_router
from backend.routes.macro import router as macro_router
from backend.routes.portfolio import router as portfolio_router
from backend.routes.price_alerts import router as price_alerts_router
from backend.routes.results import router as results_router
from backend.routes.scan import router as scan_router
from backend.routes.settings import router as settings_router
from backend.routes.stream import router as stream_router
from backend.routes.watchlist import router as watchlist_router

__all__ = [
    "auth_router", "charts_router", "history_router", "macro_router",
    "portfolio_router", "price_alerts_router",
    "results_router", "scan_router", "settings_router", "stream_router",
    "watchlist_router",
]