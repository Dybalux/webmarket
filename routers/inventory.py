from fastapi import APIRouter, Depends, HTTPException, status, Body
from typing import List
from bson import ObjectId

from models import Product, InventoryAlert, TokenData
from database import get_database
from security import get_current_admin_user
from services.inventory import (
    update_stock as _update_stock,
    add_stock as _add_stock,
    get_alerts as _get_alerts,
)
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

    return await _update_stock(
        db, product_id, new_stock, current_admin_user.user_id
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

    return await _add_stock(
        db, product_id, quantity_to_add, current_admin_user.user_id
    )


@router.get("/alerts", response_model=List[InventoryAlert])
async def get_inventory_alerts(
    limit: int = 100,
    db=Depends(get_database),
    current_admin_user: TokenData = Depends(get_current_admin_user),
):
    """[Admin] Obtiene las últimas alertas de bajo inventario."""
    return await _get_alerts(db, limit)



