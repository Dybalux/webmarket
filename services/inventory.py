"""Inventory business logic — stock updates and low-stock alerts.

Public API (see design §2.1):
  - update_stock(db, product_id, new_stock, admin_user_id) -> Product
  - add_stock(db, product_id, quantity, admin_user_id) -> Product
  - get_alerts(db, limit) -> list[InventoryAlert]
  - check_and_create_alert(db, product_id) -> None

All functions receive db: AsyncIOMotorDatabase, raise domain exceptions from
services.exceptions, and return Pydantic models or domain objects.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from models import InventoryAlert, Product
from services.exceptions import NotFoundError
import audit_logger

logger = logging.getLogger(__name__)

LOW_STOCK_THRESHOLD = 10


# ---------------------------------------------------------------------------
# Public API — stock management
# ---------------------------------------------------------------------------


async def update_stock(
    db: AsyncIOMotorDatabase,
    product_id: str,
    new_stock: int,
    admin_user_id: str,
    *,
    audit_ctx: audit_logger.AuditContext | None = None,
) -> Product:
    """Set a product's stock to an exact value (admin operation).

    Raises:
        NotFoundError: when the product_id does not exist in the database.
    """
    products = db["products"]

    # Leer stock anterior para determinar si es decremento o restauración
    current = await products.find_one({"_id": ObjectId(product_id)})
    if not current:
        raise NotFoundError("Producto no encontrado.")
    old_stock = current.get("stock", 0)

    result = await products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"stock": new_stock}},
    )

    if result.matched_count == 0:
        raise NotFoundError("Producto no encontrado.")

    await check_and_create_alert(db, product_id)

    updated = await products.find_one({"_id": ObjectId(product_id)})
    logger.info(
        "Admin %s actualizó el stock del producto %s a %s.",
        admin_user_id,
        product_id,
        new_stock,
    )

    # Fire-and-forget audit — determinar evento por delta
    delta = new_stock - old_stock
    if delta < 0:
        event = audit_logger.AuditEvent.STOCK_DECREMENTED
    else:
        event = audit_logger.AuditEvent.STOCK_RESTORED
    asyncio.create_task(
        audit_logger.log_audit_ctx(
            event,
            ctx=audit_ctx,
            details={"product_id": product_id, "old_stock": old_stock, "new_stock": new_stock},
        )
    )

    return Product(**updated)


async def add_stock(
    db: AsyncIOMotorDatabase,
    product_id: str,
    quantity: int,
    admin_user_id: str,
    *,
    audit_ctx: audit_logger.AuditContext | None = None,
) -> Product:
    """Add a quantity to a product's stock (replenishment).

    Raises:
        NotFoundError: when the product_id does not exist in the database.
    """
    products = db["products"]

    result = await products.update_one(
        {"_id": ObjectId(product_id)},
        {"$inc": {"stock": quantity}},
    )

    if result.matched_count == 0:
        raise NotFoundError("Producto no encontrado.")

    await check_and_create_alert(db, product_id)

    updated = await products.find_one({"_id": ObjectId(product_id)})
    logger.info(
        "Admin %s añadió %s unidades al stock del producto %s.",
        admin_user_id,
        quantity,
        product_id,
    )

    # Fire-and-forget audit — add_stock siempre es RESTORE
    asyncio.create_task(
        audit_logger.log_audit_ctx(
            audit_logger.AuditEvent.STOCK_RESTORED,
            ctx=audit_ctx,
            details={"product_id": product_id, "quantity_added": quantity},
        )
    )

    return Product(**updated)


async def get_alerts(
    db: AsyncIOMotorDatabase,
    limit: int = 100,
) -> list[InventoryAlert]:
    """Return the most recent low-stock alerts, newest first."""
    alerts_collection = db["inventory_alerts"]
    cursor = alerts_collection.find().sort("timestamp", -1).limit(limit)
    return [InventoryAlert(**doc) async for doc in cursor]


# ---------------------------------------------------------------------------
# Public API — alert creation (also consumed cross-module by orders)
# ---------------------------------------------------------------------------


async def check_and_create_alert(
    db: AsyncIOMotorDatabase,
    product_id: str,
) -> None:
    """Check a product's stock and insert a low-stock alert if below threshold.

    Deduplication: if an alert with the same (product_id, message) pair
    already exists, no new alert is inserted.

    This function is public (no underscore prefix) so it can be re-exported
    by routers/inventory.py for backward compatibility with routers/orders.py.
    """
    products = db["products"]
    alerts = db["inventory_alerts"]

    product = await products.find_one({"_id": ObjectId(product_id)})
    if not product:
        return

    stock = product.get("stock", 0)
    if stock > LOW_STOCK_THRESHOLD:
        return

    alert_message = (
        f"El stock del producto '{product['name']}' es bajo ({stock})."
    )

    # Dedup: skip insert when an identical (product_id, message) pair exists.
    existing = await alerts.find_one(
        {"product_id": product_id, "message": alert_message}
    )
    if existing:
        return

    alert = InventoryAlert(
        _id=None,
        product_id=product_id,
        product_name=product["name"],
        current_stock=stock,
        threshold=LOW_STOCK_THRESHOLD,
        message=alert_message,
    )
    await alerts.insert_one(alert.model_dump())
    logger.warning("ALERTA DE INVENTARIO: %s", alert_message)
