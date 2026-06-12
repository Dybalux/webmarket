from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List
from bson import ObjectId

from models import Order, OrderCreate, OrderStatus, PaymentMethod, TokenData
from database import get_database
from security import (
    get_current_active_user_id,
    get_current_admin_user,
    get_current_verified_user,
)
from services.orders import (
    create_order as _svc_create_order,
    get_my_orders as _svc_get_my_orders,
    get_order_by_id as _svc_get_order_by_id,
    select_payment_method as _svc_select_payment_method,
    update_order_status as _svc_update_order_status,
)
from services.shipping import get_shipping_prices as _svc_get_shipping_prices
from services.exceptions import (
    ComboInactiveError,
    ConcurrentStockUpdateError,
    EmptyCartError,
    ForbiddenError,
    InsufficientStockError,
    InternalError,
    InvalidStateTransitionError,
    NotFoundError,
    ShippingZoneDisabledError,
    ShippingZoneInvalidError,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /shipping-prices — public
# ---------------------------------------------------------------------------


@router.get("/shipping-prices")
async def get_shipping_prices(db=Depends(get_database)):
    """Public endpoint: enabled shipping zones and their prices."""
    return await _svc_get_shipping_prices(db)


# ---------------------------------------------------------------------------
# POST / — create order
# ---------------------------------------------------------------------------


@router.post("/", response_model=Order, status_code=status.HTTP_201_CREATED)
async def create_order_endpoint(
    order_data: OrderCreate,
    payment_method: PaymentMethod = PaymentMethod.MERCADO_PAGO,
    user_id: str = Depends(get_current_active_user_id),
    db=Depends(get_database),
    current_verified_user: TokenData = Depends(get_current_verified_user),
):
    """Create an order from the user's cart. Requires age verification."""
    try:
        return await _svc_create_order(db, user_id, order_data, payment_method)
    except EmptyCartError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except InsufficientStockError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except ComboInactiveError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except ShippingZoneInvalidError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except ShippingZoneDisabledError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except ConcurrentStockUpdateError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except InternalError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ---------------------------------------------------------------------------
# GET /me — my orders
# ---------------------------------------------------------------------------


@router.get("/me", response_model=List[Order])
async def get_my_orders(
    user_id: str = Depends(get_current_active_user_id),
    db=Depends(get_database),
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Return the authenticated user's orders (paginated, newest first)."""
    return await _svc_get_my_orders(db, user_id, limit, skip)


# ---------------------------------------------------------------------------
# POST /{order_id}/select-payment-method
# ---------------------------------------------------------------------------


@router.post("/{order_id}/select-payment-method", response_model=Order)
async def select_payment_method(
    order_id: str,
    payment_method: PaymentMethod,
    user_id: str = Depends(get_current_active_user_id),
    db=Depends(get_database),
):
    """Change the payment method on a PENDING order."""
    if not ObjectId.is_valid(order_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de pedido inválido.",
        )
    try:
        return await _svc_select_payment_method(
            db, order_id, user_id, payment_method
        )
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except ForbiddenError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ---------------------------------------------------------------------------
# GET /{order_id} — order details
# ---------------------------------------------------------------------------


@router.get("/{order_id}", response_model=Order)
async def get_order_details(
    order_id: str,
    user_id: str = Depends(get_current_active_user_id),
    db=Depends(get_database),
):
    """Return a single order, verifying ownership."""
    if not ObjectId.is_valid(order_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de pedido inválido.",
        )
    try:
        return await _svc_get_order_by_id(db, order_id, user_id)
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except ForbiddenError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ---------------------------------------------------------------------------
# PUT /admin/{order_id}/status — admin
# ---------------------------------------------------------------------------


@router.put("/admin/{order_id}/status", response_model=Order, tags=["Admin"])
async def update_order_status(
    order_id: str,
    new_status: OrderStatus,
    db=Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """[Admin] Update an order's status. Cancel/refund restores stock."""
    if not ObjectId.is_valid(order_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de pedido inválido.",
        )
    try:
        return await _svc_update_order_status(
            db, order_id, new_status, current_admin_user.user_id
        )
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
