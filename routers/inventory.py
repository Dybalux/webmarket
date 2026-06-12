"""Inventory router — thin HTTP adapter for inventory endpoints.

All business logic lives in services/inventory.py.
Endpoints: parse input → call service → translate domain exceptions
to HTTPException → serialize response.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Body
from typing import List
from bson import ObjectId

from models import Product, InventoryAlert, TokenData
from database import get_database, get_collection
from security import get_current_admin_user
from services.inventory import update_stock, add_stock, get_alerts
from services.inventory import _check_and_create_alert as _svc_check_alert
from services.exceptions import NotFoundError
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Threshold exposed for test imports.
LOW_STOCK_THRESHOLD = 10


# ---------------------------------------------------------------------------
# Backward-compat exports (for orders.py — will be removed in PR #4)
# ---------------------------------------------------------------------------


def get_alerts_collection(db=Depends(get_database)):
    """Backward-compat: orders.py still uses this FastAPI dependency.

    TODO(PR #4): remove after orders.py is refactored to use services.
    """
    return get_collection("inventory_alerts")


async def check_and_create_alert(
    products_collection, alerts_collection, product_id: str
) -> None:
    """Backward-compat wrapper — delegates to services.inventory.

    Keeps the old (products_collection, alerts_collection, product_id)
    signature so that orders.py does not break in this PR.

    TODO(PR #4): remove after orders.py calls the service directly.
    """
    # Both collections share the same database handle.
    db: AsyncIOMotorDatabase = products_collection.database
    await _svc_check_alert(db, product_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.put("/{product_id}/stock", response_model=Product)
async def update_product_stock(
    product_id: str,
    new_stock: int = Body(..., embed=True, ge=0),
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """[Admin] Set the absolute stock level of a product."""
    if not ObjectId.is_valid(product_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de producto inválido.",
        )
    try:
        return await update_stock(
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
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """[Admin] Add stock to a product (replenishment)."""
    if not ObjectId.is_valid(product_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de producto inválido.",
        )
    try:
        return await add_stock(
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
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """[Admin] Retrieve the most recent low-stock alerts."""
    return await get_alerts(db, limit)
