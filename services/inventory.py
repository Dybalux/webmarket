"""Inventory service — stock management and low-stock alerts.

Public API (async functions, receive db: AsyncIOMotorDatabase):

    update_stock(db, product_id, new_stock, admin_user_id) -> Product
        Set the stock of a product to an absolute value.
        Raises NotFoundError if the product does not exist.

    add_stock(db, product_id, quantity, admin_user_id) -> Product
        Increment the stock of a product by a given quantity.
        Raises NotFoundError if the product does not exist.

    get_alerts(db, limit=100) -> list[InventoryAlert]
        Retrieve the most recent low-stock alerts.

    check_and_create_alert(db, product_id) -> None
        Inspect product stock and create an alert if below threshold.
        Deduplicated: a matching alert (same product_id + message)
        blocks a second insert.

Private helpers:
    _check_and_create_alert(db, product_id) — implementation detail.
"""

from __future__ import annotations

import logging
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from models import Product, InventoryAlert
from services.exceptions import NotFoundError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOW_STOCK_THRESHOLD: int = 10

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _check_and_create_alert(db: AsyncIOMotorDatabase, product_id: str) -> None:
    """Inspect product stock and create an alert when it drops below threshold.

    Dedup: if an alert with the same product_id and message already exists
    (same stock level), the insert is skipped.
    """
    products_coll = db["products"]
    alerts_coll = db["inventory_alerts"]

    product = await products_coll.find_one({"_id": ObjectId(product_id)})

    if product and product.get("stock", 0) <= _LOW_STOCK_THRESHOLD:
        alert_message = (
            f"El stock del producto '{product['name']}' es bajo ({product['stock']})."
        )

        # Avoid duplicate alerts for the same product + stock level.
        existing = await alerts_coll.find_one(
            {"product_id": product_id, "message": alert_message}
        )
        if not existing:
            alert = InventoryAlert(
                _id=None,
                product_id=product_id,
                product_name=product["name"],
                current_stock=product["stock"],
                threshold=_LOW_STOCK_THRESHOLD,
                message=alert_message,
            )
            await alerts_coll.insert_one(alert.model_dump())
            logger.warning(f"ALERTA DE INVENTARIO: {alert_message}")


# Alias for backward compatibility — orders.py imports this name from
# routers/inventory.py, which re-exports this symbol.
# TODO(PR #4): remove after orders.py is refactored.
check_and_create_alert = _check_and_create_alert


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def update_stock(
    db: AsyncIOMotorDatabase,
    product_id: str,
    new_stock: int,
    admin_user_id: str,
) -> Product:
    """Set the absolute stock level of a product.

    Args:
        db: MongoDB database handle.
        product_id: Target product ID string (must be a valid ObjectId).
        new_stock: New absolute stock value (≥ 0).
        admin_user_id: The admin performing the operation.

    Returns:
        The updated Product model.

    Raises:
        NotFoundError: If no product matches product_id.
    """
    products_coll = db["products"]

    result = await products_coll.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"stock": new_stock}},
    )

    if result.matched_count == 0:
        raise NotFoundError("Producto no encontrado.")

    await _check_and_create_alert(db, product_id)

    updated = await products_coll.find_one({"_id": ObjectId(product_id)})
    logger.info(
        "Admin %s updated stock of product %s to %d.",
        admin_user_id,
        product_id,
        new_stock,
    )
    return Product(**updated)


async def add_stock(
    db: AsyncIOMotorDatabase,
    product_id: str,
    quantity: int,
    admin_user_id: str,
) -> Product:
    """Add stock to a product (replenishment).

    Args:
        db: MongoDB database handle.
        product_id: Target product ID string.
        quantity: Amount to add (> 0).
        admin_user_id: The admin performing the operation.

    Returns:
        The updated Product model.

    Raises:
        NotFoundError: If no product matches product_id.
    """
    products_coll = db["products"]

    result = await products_coll.update_one(
        {"_id": ObjectId(product_id)},
        {"$inc": {"stock": quantity}},
    )

    if result.matched_count == 0:
        raise NotFoundError("Producto no encontrado.")

    await _check_and_create_alert(db, product_id)

    updated = await products_coll.find_one({"_id": ObjectId(product_id)})
    logger.info(
        "Admin %s added %d units to stock of product %s.",
        admin_user_id,
        quantity,
        product_id,
    )
    return Product(**updated)


async def get_alerts(
    db: AsyncIOMotorDatabase,
    limit: int = 100,
) -> list[InventoryAlert]:
    """Retrieve the most recent low-stock alerts.

    Args:
        db: MongoDB database handle.
        limit: Maximum number of alerts to return.

    Returns:
        List of InventoryAlert models, newest first.
    """
    alerts_coll = db["inventory_alerts"]
    cursor = alerts_coll.find().sort("timestamp", -1).limit(limit)
    return [InventoryAlert(**doc) async for doc in cursor]
