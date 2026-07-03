"""Trading order execution routes — place/cancel orders, manage positions.

Endpoints
---------
POST   /api/v1/trading/{exchange}/order              — place a new order
DELETE /api/v1/trading/{exchange}/order/{order_id}    — cancel an open order
GET    /api/v1/trading/{exchange}/orders/open        — list open orders
POST   /api/v1/trading/{exchange}/position/close     — close a position
POST   /api/v1/trading/{exchange}/position/leverage   — change leverage

All endpoints require JWT auth (``Depends(get_current_user)``).

**Safety gate**: Trading is disabled by default. Set the
``MIRAJ_TRADING_ENABLED=true`` environment variable to enable live order
execution. When disabled, every endpoint returns ``503 Service Unavailable``
with a descriptive message so the frontend can degrade gracefully.

Error mapping
-------------
* 401 — not authenticated (raised by ``get_current_user``)
* 403 — trading is disabled (no env var)
* 404 — exchange not in the supported-exchanges list / order not found
* 400 — invalid order parameters (missing price for limit, bad side, etc.)
* 429 — exchange rate-limited the request
* 502 — exchange timeout, network error, or other upstream failure
* 501 — ccxt is not importable
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_session
from backend.models import User
from backend.services import exchange_service
from backend.services.exchange_service import (
    SUPPORTED_EXCHANGES,
    ExchangeAuthError,
    ExchangeError,
    ExchangeRateLimitError,
    ExchangeTimeoutError,
    get_exchange,
    is_ccxt_available,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trading", tags=["trading"])

#: Whether live trading is enabled. Must be explicitly set to "true" to allow
#: order execution. This is a safety gate — trading is dangerous and should
#: be opt-in.
TRADING_ENABLED = os.environ.get("MIRAJ_TRADING_ENABLED", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


# ── Guards ─────────────────────────────────────────────────────────────────


def _require_trading_enabled() -> None:
    """Raise 503 if trading is not enabled via the MIRAJ_TRADING_ENABLED env."""
    if not TRADING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Trading is disabled. Set MIRAJ_TRADING_ENABLED=true in the "
                "backend environment to enable live order execution."
            ),
            headers={"X-Error-Code": "trading_disabled"},
        )


def _require_supported_exchange(exchange: str) -> str:
    """Return the normalised exchange slug or raise HTTP 404 / 501."""
    exchange_slug = exchange.strip().lower()
    if not is_ccxt_available():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="ccxt package is not installed — trading is disabled",
            headers={"X-Error-Code": "ccxt_not_installed"},
        )
    exchange_service._load_supported_exchanges()
    if exchange_slug not in SUPPORTED_EXCHANGES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Exchange '{exchange_slug}' is not supported. "
                f"Supported: {sorted(SUPPORTED_EXCHANGES)}"
            ),
            headers={"X-Error-Code": "unsupported_exchange"},
        )
    return exchange_slug


def _map_exchange_error(exc: ExchangeError, action: str) -> HTTPException:
    """Map an :class:`ExchangeError` to an ``HTTPException``."""
    if isinstance(exc, ExchangeRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.args[0] if exc.args else "Rate limited by exchange",
            headers={"X-Error-Code": exc.code, "Retry-After": "30"},
        )
    if isinstance(exc, ExchangeAuthError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Exchange authentication failed during {action}: {exc}. "
                "Your API key may be invalid or revoked — please reconnect."
            ),
            headers={"X-Error-Code": exc.code},
        )
    if isinstance(exc, ExchangeTimeoutError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Exchange request timed out during {action}: {exc}",
            headers={"X-Error-Code": exc.code},
        )
    # ccxt-specific errors that map to 400 (bad request)
    try:
        import ccxt  # noqa: PLC0415

        if isinstance(exc, (ccxt.InsufficientFunds, ccxt.InvalidOrder, ccxt.BadSymbol)):
            return HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Order rejected by exchange: {exc}",
                headers={"X-Error-Code": "invalid_order"},
            )
    except ImportError:
        pass
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Exchange error during {action}: {exc}",
        headers={"X-Error-Code": exc.code},
    )


# ── Pydantic request/response schemas ───────────────────────────────────────


class PlaceOrderRequest(BaseModel):
    """Body for POST /order — place a new buy/sell order."""

    symbol: str = Field(..., min_length=1, description="Trading symbol, e.g. BTC/USDT:USDT")
    type: str = Field("limit", pattern="^(limit|market)$", description="Order type")
    side: str = Field(..., pattern="^(buy|sell)$", description="Order side")
    amount: float = Field(..., gt=0, description="Order amount (contracts/base units)")
    price: Optional[float] = Field(None, gt=0, description="Limit price (required for limit orders)")
    reduce_only: bool = Field(False, description="If true, order can only reduce an existing position")
    leverage: Optional[int] = Field(None, ge=1, le=125, description="Set leverage before placing order")


class ClosePositionRequest(BaseModel):
    """Body for POST /position/close — close a position."""

    symbol: str = Field(..., min_length=1, description="Position symbol")
    side: str = Field(..., pattern="^(long|short)$", description="Position side to close")


class SetLeverageRequest(BaseModel):
    """Body for POST /position/leverage — change leverage."""

    symbol: str = Field(..., min_length=1, description="Trading symbol")
    leverage: int = Field(..., ge=1, le=125, description="Leverage multiplier")


class OrderResponse(BaseModel):
    """Response for a placed/cancelled order."""

    id: str
    symbol: str
    type: str
    side: str
    amount: float
    price: Optional[float] = None
    filled: float = 0.0
    remaining: float = 0.0
    status: str
    reduce_only: Optional[bool] = None
    timestamp: Optional[int] = None
    cost: Optional[float] = None
    fee: Optional[Dict[str, Any]] = None


class ClosePositionResponse(BaseModel):
    """Response for closing a position."""

    success: bool
    symbol: str
    side: str
    message: str = ""


class LeverageResponse(BaseModel):
    """Response for setting leverage."""

    success: bool
    symbol: str
    leverage: int
    message: str = ""


class TradingStatusResponse(BaseModel):
    """Response for the trading status endpoint."""

    enabled: bool


# ── Helper to run blocking ccxt calls in a thread ──────────────────────────


async def _run_blocking(func, *args, **kwargs) -> Any:
    """Run a blocking ccxt method in a thread pool."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _serialize_order(order: Dict[str, Any]) -> OrderResponse:
    """Convert a raw ccxt order dict into an OrderResponse."""
    return OrderResponse(
        id=str(order.get("id", "")),
        symbol=order.get("symbol", ""),
        type=order.get("type", "limit"),
        side=order.get("side", "buy"),
        amount=float(order.get("amount", 0) or 0),
        price=float(order["price"]) if order.get("price") is not None else None,
        filled=float(order.get("filled", 0) or 0),
        remaining=float(order.get("remaining", 0) or 0),
        status=order.get("status", "open"),
        reduce_only=order.get("reduceOnly"),
        timestamp=order.get("timestamp"),
        cost=float(order.get("cost", 0)) if order.get("cost") is not None else None,
        fee=order.get("fee"),
    )


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=TradingStatusResponse,
    summary="Check if trading is enabled",
)
async def get_trading_status(
    current_user: User = Depends(get_current_user),
) -> TradingStatusResponse:
    """Return whether live trading is enabled via the MIRAJ_TRADING_ENABLED env var.

    The frontend uses this to show/hide the trading UI and display a warning
    when trading is disabled.
    """
    return TradingStatusResponse(enabled=TRADING_ENABLED)


@router.post(
    "/{exchange}/order",
    response_model=OrderResponse,
    responses={
        400: {"description": "Invalid order parameters"},
        403: {"description": "Trading is disabled"},
        404: {"description": "Unsupported exchange"},
        429: {"description": "Rate limited"},
        502: {"description": "Exchange error"},
    },
)
async def place_order(
    exchange: str,
    body: PlaceOrderRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    """Place a new order on the given exchange.

    Uses ccxt ``createOrder()``. For limit orders, ``price`` is required.
    If ``leverage`` is provided, ``setLeverage()`` is called before placing
    the order.
    """
    _require_trading_enabled()
    exchange_slug = _require_supported_exchange(exchange)

    # Validate limit orders have a price
    if body.type == "limit" and body.price is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit orders require a price",
            headers={"X-Error-Code": "missing_price"},
        )

    try:
        exchange_instance = await get_exchange(
            user_id=current_user.id,
            exchange_name=exchange_slug,
            db_session=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
            headers={"X-Error-Code": "no_api_keys"},
        ) from exc

    try:
        # Set leverage if provided
        if body.leverage is not None:
            try:
                await _run_blocking(
                    exchange_instance.set_leverage,
                    mode=1,  # isolated margin
                    leverage=body.leverage,
                    symbol=body.symbol,
                )
            except Exception as exc:
                # Some exchanges don't support setLeverage or it fails for
                # spot markets — log and continue.
                logger.warning(
                    "setLeverage failed for %s on %s (continuing): %s",
                    body.symbol, exchange_slug, exc,
                )

        # Build ccxt createOrder params
        params: Dict[str, Any] = {}
        if body.reduce_only:
            params["reduceOnly"] = True

        order = await _run_blocking(
            exchange_instance.create_order,
            symbol=body.symbol,
            type=body.type,
            side=body.side,
            amount=body.amount,
            price=body.price if body.type == "limit" else None,
            params=params,
        )

        logger.info(
            "Order placed: user=%d exchange=%s symbol=%s %s %s amount=%s price=%s id=%s",
            current_user.id, exchange_slug, body.symbol,
            body.side, body.type, body.amount, body.price, order.get("id"),
        )
        return _serialize_order(order)

    except ExchangeError as exc:
        raise _map_exchange_error(exc, action="place_order") from exc
    except Exception as exc:
        # Translate ccxt errors via the helper
        translated = exchange_service._translate_ccxt_error(exc)
        if translated is not exc:
            raise _map_exchange_error(translated, action="place_order") from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected error placing order: {exc}",
            headers={"X-Error-Code": "unexpected_error"},
        ) from exc


@router.delete(
    "/{exchange}/order/{order_id}",
    response_model=OrderResponse,
    responses={
        403: {"description": "Trading is disabled"},
        404: {"description": "Order or exchange not found"},
        429: {"description": "Rate limited"},
        502: {"description": "Exchange error"},
    },
)
async def cancel_order(
    exchange: str,
    order_id: str,
    symbol: str = "",
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    """Cancel an open order by its exchange-assigned id.

    The ``symbol`` query parameter is required by most exchanges to identify
    the order. Pass it as ``?symbol=BTC/USDT:USDT``.
    """
    _require_trading_enabled()
    exchange_slug = _require_supported_exchange(exchange)

    if not symbol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The 'symbol' query parameter is required to cancel an order",
            headers={"X-Error-Code": "missing_symbol"},
        )

    try:
        exchange_instance = await get_exchange(
            user_id=current_user.id,
            exchange_name=exchange_slug,
            db_session=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
            headers={"X-Error-Code": "no_api_keys"},
        ) from exc

    try:
        order = await _run_blocking(
            exchange_instance.cancel_order,
            id=order_id,
            symbol=symbol,
        )
        logger.info(
            "Order cancelled: user=%d exchange=%s order_id=%s",
            current_user.id, exchange_slug, order_id,
        )
        return _serialize_order(order)

    except ExchangeError as exc:
        raise _map_exchange_error(exc, action="cancel_order") from exc
    except Exception as exc:
        translated = exchange_service._translate_ccxt_error(exc)
        if translated is not exc:
            raise _map_exchange_error(translated, action="cancel_order") from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected error cancelling order: {exc}",
            headers={"X-Error-Code": "unexpected_error"},
        ) from exc


@router.get(
    "/{exchange}/orders/open",
    response_model=List[OrderResponse],
    responses={
        403: {"description": "Trading is disabled"},
        404: {"description": "Unsupported exchange"},
        429: {"description": "Rate limited"},
        502: {"description": "Exchange error"},
    },
)
async def list_open_orders(
    exchange: str,
    symbol: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[OrderResponse]:
    """List all open orders for the current user on the given exchange.

    Optionally filter by symbol via ``?symbol=BTC/USDT:USDT``.
    Uses ccxt ``fetchOpenOrders()``.
    """
    _require_trading_enabled()
    exchange_slug = _require_supported_exchange(exchange)

    try:
        exchange_instance = await get_exchange(
            user_id=current_user.id,
            exchange_name=exchange_slug,
            db_session=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
            headers={"X-Error-Code": "no_api_keys"},
        ) from exc

    try:
        kwargs: Dict[str, Any] = {}
        if symbol:
            kwargs["symbol"] = symbol

        orders = await _run_blocking(
            exchange_instance.fetch_open_orders,
            **kwargs,
        )
        return [_serialize_order(o) for o in orders]

    except ExchangeError as exc:
        raise _map_exchange_error(exc, action="fetch_open_orders") from exc
    except Exception as exc:
        translated = exchange_service._translate_ccxt_error(exc)
        if translated is not exc:
            raise _map_exchange_error(translated, action="fetch_open_orders") from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected error fetching open orders: {exc}",
            headers={"X-Error-Code": "unexpected_error"},
        ) from exc


@router.post(
    "/{exchange}/position/close",
    response_model=ClosePositionResponse,
    responses={
        403: {"description": "Trading is disabled"},
        404: {"description": "Unsupported exchange"},
        429: {"description": "Rate limited"},
        502: {"description": "Exchange error"},
    },
)
async def close_position(
    exchange: str,
    body: ClosePositionRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ClosePositionResponse:
    """Close a futures position.

    Uses ccxt ``closePosition()`` when available. Falls back to placing a
    reduce-only market order of the opposite side if ``closePosition`` is not
    supported by the exchange.

    *body.side* is the position side to close (``"long"`` or ``"short"``).
    ccxt's ``closePosition`` expects the **position side**, not the order side.
    """
    _require_trading_enabled()
    exchange_slug = _require_supported_exchange(exchange)

    try:
        exchange_instance = await get_exchange(
            user_id=current_user.id,
            exchange_name=exchange_slug,
            db_session=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
            headers={"X-Error-Code": "no_api_keys"},
        ) from exc

    try:
        import ccxt  # noqa: PLC0415

        # Determine the order side that closes the position.
        # Closing a long → sell. Closing a short → buy.
        order_side = "sell" if body.side == "long" else "buy"

        # Try ccxt's native closePosition first (cleaner, handles size).
        closed = False
        try:
            await _run_blocking(
                exchange_instance.close_position,
                symbol=body.symbol,
                side=body.side,
            )
            closed = True
        except (ccxt.NotSupported, ccxt.BadSymbol, AttributeError):
            pass
        except Exception as exc:
            logger.warning(
                "closePosition failed for %s (%s): %s — falling back to reduce-only order",
                body.symbol, body.side, exc,
            )

        # Fallback: fetch position size and place a reduce-only market order.
        if not closed:
            try:
                positions = await _run_blocking(
                    exchange_instance.fetch_positions,
                    symbols=[body.symbol],
                )
            except Exception:
                positions = await _run_blocking(
                    exchange_instance.fetch_positions,
                )

            position = None
            for pos in positions:
                pos_side = pos.get("side", "")
                pos_symbol = pos.get("symbol", "")
                if pos_symbol == body.symbol and (pos_side == body.side or not pos_side):
                    position = pos
                    break

            if position is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No open {body.side} position found for {body.symbol}",
                    headers={"X-Error-Code": "position_not_found"},
                )

            contracts = float(position.get("contracts", 0) or position.get("size", 0) or 0)
            if contracts == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Position {body.symbol} ({body.side}) has zero size — nothing to close",
                    headers={"X-Error-Code": "position_empty"},
                )

            await _run_blocking(
                exchange_instance.create_order,
                symbol=body.symbol,
                type="market",
                side=order_side,
                amount=abs(contracts),
                params={"reduceOnly": True},
            )
            closed = True

        logger.info(
            "Position closed: user=%d exchange=%s symbol=%s side=%s",
            current_user.id, exchange_slug, body.symbol, body.side,
        )
        return ClosePositionResponse(
            success=True,
            symbol=body.symbol,
            side=body.side,
            message="Position closed successfully",
        )

    except HTTPException:
        raise
    except ExchangeError as exc:
        raise _map_exchange_error(exc, action="close_position") from exc
    except Exception as exc:
        translated = exchange_service._translate_ccxt_error(exc)
        if translated is not exc:
            raise _map_exchange_error(translated, action="close_position") from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected error closing position: {exc}",
            headers={"X-Error-Code": "unexpected_error"},
        ) from exc


@router.post(
    "/{exchange}/position/leverage",
    response_model=LeverageResponse,
    responses={
        403: {"description": "Trading is disabled"},
        404: {"description": "Unsupported exchange"},
        429: {"description": "Rate limited"},
        502: {"description": "Exchange error"},
    },
)
async def set_leverage(
    exchange: str,
    body: SetLeverageRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LeverageResponse:
    """Change the leverage for a symbol on the given exchange.

    Uses ccxt ``setLeverage()``.
    """
    _require_trading_enabled()
    exchange_slug = _require_supported_exchange(exchange)

    try:
        exchange_instance = await get_exchange(
            user_id=current_user.id,
            exchange_name=exchange_slug,
            db_session=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
            headers={"X-Error-Code": "no_api_keys"},
        ) from exc

    try:
        await _run_blocking(
            exchange_instance.set_leverage,
            leverage=body.leverage,
            symbol=body.symbol,
        )
        logger.info(
            "Leverage set: user=%d exchange=%s symbol=%s leverage=%d",
            current_user.id, exchange_slug, body.symbol, body.leverage,
        )
        return LeverageResponse(
            success=True,
            symbol=body.symbol,
            leverage=body.leverage,
            message=f"Leverage set to {body.leverage}x",
        )

    except ExchangeError as exc:
        raise _map_exchange_error(exc, action="set_leverage") from exc
    except Exception as exc:
        translated = exchange_service._translate_ccxt_error(exc)
        if translated is not exc:
            raise _map_exchange_error(translated, action="set_leverage") from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected error setting leverage: {exc}",
            headers={"X-Error-Code": "unexpected_error"},
        ) from exc
