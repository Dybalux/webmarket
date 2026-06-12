from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from models import Cart, CartItem, CartDetailed, TokenData
from database import get_database
from security import get_current_active_user_id, get_current_verified_user

# --- Service layer ---
from services.cart import (
    get_cart as _svc_get_cart,
    add_to_cart as _svc_add_to_cart,
    update_cart_item as _svc_update_cart_item,
    remove_from_cart as _svc_remove_from_cart,
    clear_cart as _svc_clear_cart,
    cleanup_cart as _svc_cleanup_cart,
    validate_cart_stock as _svc_validate_cart_stock,
)
from services.exceptions import (
    CartItemNotFoundError,
    InsufficientStockError,
    NotFoundError,
)

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /cart — detailed view
# ---------------------------------------------------------------------------


@router.get("/", response_model=CartDetailed)
async def get_cart(
    user_id: str = Depends(get_current_active_user_id),
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_verified_user: TokenData = Depends(get_current_verified_user),
):
    """Get the user's cart with detailed product/combo information."""
    return await _svc_get_cart(db, user_id)


# ---------------------------------------------------------------------------
# POST /cart/add — add or update an item
# ---------------------------------------------------------------------------


@router.post("/add", response_model=Cart)
async def add_to_cart(
    cart_item_data: CartItem,
    user_id: str = Depends(get_current_active_user_id),
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_verified_user: TokenData = Depends(get_current_verified_user),
):
    """Add a product or combo to the user's cart, or update its quantity."""
    if not ObjectId.is_valid(cart_item_data.product_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de producto/combo inválido.",
        )
    try:
        return await _svc_add_to_cart(
            db, user_id, cart_item_data.product_id, cart_item_data.quantity
        )
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except InsufficientStockError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=e.detail
        )


# ---------------------------------------------------------------------------
# PUT /cart/update — change item quantity
# ---------------------------------------------------------------------------


@router.put("/update", response_model=Cart)
async def update_cart_item_quantity(
    cart_item_data: CartItem,
    user_id: str = Depends(get_current_active_user_id),
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_verified_user: TokenData = Depends(get_current_verified_user),
):
    """Update the quantity of an item. Quantity 0 removes it."""
    if not ObjectId.is_valid(cart_item_data.product_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de producto/combo inválido.",
        )
    try:
        return await _svc_update_cart_item(
            db, user_id, cart_item_data.product_id, cart_item_data.quantity
        )
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except InsufficientStockError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=e.detail
        )
    except CartItemNotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ---------------------------------------------------------------------------
# DELETE /cart/remove/{product_id} — remove an item
# ---------------------------------------------------------------------------


@router.delete("/remove/{product_id}", response_model=Cart)
async def remove_from_cart(
    product_id: str,
    user_id: str = Depends(get_current_active_user_id),
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_verified_user: TokenData = Depends(get_current_verified_user),
):
    """Remove a product from the user's cart."""
    if not ObjectId.is_valid(product_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de producto inválido.",
        )
    try:
        return await _svc_remove_from_cart(db, user_id, product_id)
    except CartItemNotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ---------------------------------------------------------------------------
# POST /cart/cleanup — remove invalid items
# ---------------------------------------------------------------------------


@router.post("/cleanup")
async def cleanup_cart(
    user_id: str = Depends(get_current_active_user_id),
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_verified_user: TokenData = Depends(get_current_verified_user),
):
    """Clean up the cart by removing items that no longer exist or are inactive."""
    return await _svc_cleanup_cart(db, user_id)


# ---------------------------------------------------------------------------
# GET /cart/validate-stock — stock validation
# ---------------------------------------------------------------------------


@router.get("/validate-stock")
async def validate_cart_stock(
    user_id: str = Depends(get_current_active_user_id),
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_verified_user: TokenData = Depends(get_current_verified_user),
):
    """Validate stock availability for all items in the cart."""
    return await _svc_validate_cart_stock(db, user_id)


# ---------------------------------------------------------------------------
# DELETE /cart/clear — empty the cart
# ---------------------------------------------------------------------------


@router.delete("/clear", response_model=Cart)
async def clear_cart(
    user_id: str = Depends(get_current_active_user_id),
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_verified_user: TokenData = Depends(get_current_verified_user),
):
    """Empty the user's cart completely."""
    return await _svc_clear_cart(db, user_id)
