from fastapi import APIRouter, Depends, HTTPException, status, Body
from typing import List
from bson import ObjectId

from models import Product, InventoryAlert, TokenData
from database import get_database, get_collection
from security import get_current_admin_user
from services.inventory import (
    update_stock as _update_stock,
    add_stock as _add_stock,
    get_alerts as _get_alerts,
    check_and_create_alert as _svc_check_and_create_alert,
    LOW_STOCK_THRESHOLD as _LOW_STOCK_THRESHOLD,
)
from services.exceptions import NotFoundError
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Endpoints — thin HTTP adapters
# ---------------------------------------------------------------------------


@router.put("/{product_id}/stock", response_model=Product)
async def update_product_stock(
    product_id: str,
    new_stock: int = Body(..., embed=True, ge=0),
    db=Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """[Admin] Establece manualmente el stock de un producto específico."""
    if not ObjectId.is_valid(product_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de producto inválido.",
        )

    try:
        return await _update_stock(
            db, product_id, new_stock, current_admin_user.user_id
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado.",
        )


@router.put("/{product_id}/stock/add", response_model=Product)
async def add_to_product_stock(
    product_id: str,
    quantity_to_add: int = Body(..., embed=True, gt=0),
    db=Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """[Admin] Añade una cantidad al stock de un producto (reposición)."""
    if not ObjectId.is_valid(product_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de producto inválido.",
        )

    try:
        return await _add_stock(
            db, product_id, quantity_to_add, current_admin_user.user_id
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado.",
        )


@router.get("/alerts", response_model=List[InventoryAlert])
async def get_inventory_alerts(
    limit: int = 100,
    db=Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """[Admin] Obtiene las últimas alertas de bajo inventario."""
    return await _get_alerts(db, limit)


# ---------------------------------------------------------------------------
# Backward-compat shims — to be removed in PR #4 (OrdersService refactor)
# ---------------------------------------------------------------------------

# Re-export LOW_STOCK_THRESHOLD so existing imports from routers.inventory
# (e.g. tests/unit/test_inventory_alerts.py before fixture update) still work.
LOW_STOCK_THRESHOLD = _LOW_STOCK_THRESHOLD


async def check_and_create_alert(
    products_collection, alerts_collection, product_id: str
):
    """Backward-compat wrapper — delegates to services.inventory.check_and_create_alert.

    Preserves the old (products_col, alerts_col, product_id) signature so
    routers/orders.py continues to work until PR #4 (OrdersService refactor)
    removes this shim and passes db directly.
    """
    db = products_collection.database
    return await _svc_check_and_create_alert(db, product_id)


def get_alerts_collection(db=Depends(get_database)):
    """Backward-compat dep for routers/orders.py — remove in PR #4."""
    return get_collection("inventory_alerts")
