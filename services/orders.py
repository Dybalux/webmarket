"""Order business logic — creation, status management, and listing.

Public API (see design §2.5):
  create_order, get_my_orders, get_order_by_id, select_payment_method,
  update_order_status.

Preserves $gte guard + manual rollback (add-stock-tests bug fix).
Preserves stock-restore indentation fix inside the cancel/refund if-block.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from email_service import send_new_order_notification
from models import Cart, Order, OrderCreate, OrderStatus, PaymentMethod
from services.exceptions import (
    EmptyCartError, ForbiddenError, InternalError,
    InvalidStateTransitionError, NotFoundError,
    ShippingZoneDisabledError, ShippingZoneInvalidError,
)
from services.inventory import check_and_create_alert
from services.orders_helpers import _decrement_stock_batch, _resolve_cart_item
from services.shipping import calculate_shipping_cost
from utils.money import decimalize_doc, quantize_money

logger = logging.getLogger(__name__)

_VALID_ZONES = frozenset({"central", "remote", "pickup"})
_ZONE_NAMES = {"central": "Envío a zona céntrica",
               "remote": "Envío a zonas alejadas",
               "pickup": "Retiro en persona"}
_ZONE_KEYS = {"central": "central_zone_enabled",
              "remote": "remote_zone_enabled",
              "pickup": "pickup_enabled"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_order(
    db: AsyncIOMotorDatabase, user_id: str,
    order_data: OrderCreate, payment_method: PaymentMethod,
) -> Order:
    """Full flow: cart → resolve items → validate shipping → decrement stock
    ($gte guard + rollback) → insert order → clear cart → alerts → email."""

    # 1. Cart
    cdoc = await db["carts"].find_one({"user_id": user_id})
    if not cdoc or not cdoc.get("items"):
        raise EmptyCartError("Tu carrito está vacío.")
    cdoc["_id"] = str(cdoc["_id"])
    cart = Cart(**cdoc)

    # 2. Shipping zone
    zone = order_data.shipping_zone
    if zone not in _VALID_ZONES:
        raise ShippingZoneInvalidError(
            "Zona de envío inválida. Debe ser 'central', 'remote' o 'pickup'.")
    ss = await db["shipping_settings"].find_one({})
    if ss and not ss.get(_ZONE_KEYS[zone], True):
        raise ShippingZoneDisabledError(
            f"{_ZONE_NAMES[zone]} no está disponible actualmente. "
            f"Por favor, selecciona otra opción de envío.")

    # 3. Resolve items
    ois, all_ops, total = [], [], Decimal("0.00")
    for ci in cart.items:
        oi, ops = await _resolve_cart_item(db, ci)
        ois.append(oi); all_ops.extend(ops)
        total += oi.price_at_purchase * oi.quantity

    # 4. Shipping cost
    n_items = sum(i.quantity for i in cart.items)
    has_c = any(oi.name.endswith("(Combo)") for oi in ois)
    shipping = await calculate_shipping_cost(db, zone, n_items, has_c)

    # 5. Build + insert order
    order_total = quantize_money(total + shipping)
    new_order = Order(
        user_id=user_id, items=ois, total_amount=order_total,
        status=OrderStatus.PENDING, shipping_address=order_data.shipping_address,
        shipping_zone=zone, shipping_cost=shipping, payment_method=payment_method)

    await _decrement_stock_batch(db, all_ops)

    seen: set[str] = set()
    for op in all_ops:
        pid = str(op["id"])
        if pid not in seen:
            seen.add(pid); await check_and_create_alert(db, pid)

    odict = new_order.model_dump(exclude={"_id"}, by_alias=False)
    result = await db["orders"].insert_one(decimalize_doc(odict))
    if not result.inserted_id:
        raise InternalError("No se pudo crear el pedido.")

    await db["carts"].update_one({"user_id": user_id}, {"$set": {"items": []}})
    logger.info("Order %s created for user %s.", result.inserted_id, user_id)

    # Email (best-effort)
    created = await db["orders"].find_one({"_id": result.inserted_id})
    try:
        u = await db["users"].find_one({"_id": ObjectId(user_id)})
        email = u.get("email", "email-no-disponible") if u else "email-no-disponible"
        await send_new_order_notification(
            str(result.inserted_id), email, order_total, payment_method.value)
    except Exception as exc:
        logger.error("Email notify failed: %s", exc)

    return Order(**created)


async def get_my_orders(
    db: AsyncIOMotorDatabase, user_id: str, limit: int = 50, skip: int = 0,
) -> List[Order]:
    """User's orders, newest first (paginated)."""
    cur = db["orders"].find({"user_id": user_id}).sort("created_at", -1)
    return [Order(**d) async for d in cur.skip(skip).limit(limit)]


async def get_order_by_id(
    db: AsyncIOMotorDatabase, order_id: str, user_id: str,
) -> Order:
    """Single order with ownership check."""
    doc = await db["orders"].find_one({"_id": ObjectId(order_id)})
    if not doc:
        raise NotFoundError("Pedido no encontrado.")
    if doc["user_id"] != user_id:
        raise ForbiddenError("No tienes permiso para ver este pedido.")
    return Order(**doc)


async def select_payment_method(
    db: AsyncIOMotorDatabase, order_id: str, user_id: str,
    payment_method: PaymentMethod,
) -> Order:
    """Change payment method on a PENDING order."""
    doc = await db["orders"].find_one({"_id": ObjectId(order_id)})
    if not doc:
        raise NotFoundError("Pedido no encontrado.")
    if doc["user_id"] != user_id:
        raise ForbiddenError("Este pedido no te pertenece.")
    if doc["status"] != OrderStatus.PENDING.value:
        raise InvalidStateTransitionError(
            f"No se puede cambiar el método de pago. "
            f"El pedido está en estado '{doc['status']}'.")

    await db["orders"].update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"payment_method": payment_method.value,
                  "updated_at": datetime.now(tz=timezone.utc)}})
    logger.info("User %s → payment %s for order %s.",
                user_id, payment_method.value, order_id)
    return Order(**(await db["orders"].find_one({"_id": ObjectId(order_id)})))


async def update_order_status(
    db: AsyncIOMotorDatabase, order_id: str, new_status: OrderStatus,
    admin_user_id: str,
) -> Order:
    """Admin: update order status. Cancel/refund restores stock."""
    doc = await db["orders"].find_one({"_id": ObjectId(order_id)})
    if not doc:
        raise NotFoundError("Pedido no encontrado.")

    cur = str(doc["status"])

    # Stock restore inside the if (indentation fix from add-stock-tests).
    if new_status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED) and (
        cur not in (OrderStatus.CANCELLED.value, OrderStatus.REFUNDED.value)):
        logger.info("Order %s → cancel/refund — restoring stock.", order_id)
        for item in doc["items"]:
            try:
                await db["products"].update_one(
                    {"_id": ObjectId(item["product_id"])},
                    {"$inc": {"stock": item["quantity"]}})
            except Exception:
                logger.error("Skip stock restore: %s", item["product_id"])

    await db["orders"].update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"status": new_status.value,
                  "updated_at": datetime.now(tz=timezone.utc)}})
    updated = await db["orders"].find_one({"_id": ObjectId(order_id)})
    logger.info("Admin %s → order %s = '%s'.",
                admin_user_id, order_id, new_status.value)
    return Order(**updated)
