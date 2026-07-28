"""Private helpers for services/orders.py.

These functions are NOT part of the public API — they exist solely to keep
``services/orders.py`` under the 160-LOC budget.

  - _resolve_cart_item: resolve a cart item (product or combo) into an
    OrderItem and a list of stock-decrement operations.
  - _decrement_stock_batch: $gte-guarded batch stock decrement with manual
    rollback on race condition.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import List

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from models import OrderItem
from services.exceptions import (
    ComboInactiveError,
    ConcurrentStockUpdateError,
    InsufficientStockError,
    NotFoundError,
)
from services.pricing import get_adjusted_price
from utils.money import from_decimal128

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stock operations
# ---------------------------------------------------------------------------


async def _decrement_stock_batch(
    db: AsyncIOMotorDatabase,
    items: list[dict],
) -> None:
    """Decrement product stock with $gte guard; roll back on race condition.

    Each ``item`` dict: ``id`` (ObjectId), ``quantity_to_decrement`` (int),
    ``name`` (str, for error messages).
    """
    products = db["products"]
    applied: list[dict] = []

    for p in items:
        result = await products.update_one(
            {"_id": p["id"], "stock": {"$gte": p["quantity_to_decrement"]}},
            {"$inc": {"stock": -p["quantity_to_decrement"]}},
        )
        if result.modified_count == 0:
            for rollback_p in applied:
                await products.update_one(
                    {"_id": rollback_p["id"]},
                    {"$inc": {"stock": rollback_p["quantity_to_decrement"]}},
                )
            product_doc = await products.find_one({"_id": p["id"]})
            name = product_doc["name"] if product_doc else "desconocido"
            raise ConcurrentStockUpdateError(
                f"Stock insuficiente para '{name}' debido a una compra "
                f"concurrente. Por favor, intentá nuevamente."
            )
        applied.append(p)


# ---------------------------------------------------------------------------
# Cart item resolution (product vs combo)
# ---------------------------------------------------------------------------


async def _resolve_cart_item(
    db: AsyncIOMotorDatabase,
    item,
) -> tuple[OrderItem, list[dict]]:
    """Resolve a single cart item into an OrderItem + stock-decrement ops.

    Returns:
        (order_item, decrement_ops) where *decrement_ops* is
        ``[{"id": ObjectId, "quantity_to_decrement": int, "name": str}, ...]``.
    """
    products = db["products"]
    combos = db["combos"]

    # ── Try as a regular product ──
    product = await products.find_one({"_id": ObjectId(item.product_id)})
    if product:
        stock = product.get("stock", 0)
        if stock < item.quantity:
            raise InsufficientStockError(
                f"Stock insuficiente para '{product['name']}'. "
                f"Disponible: {stock}, Solicitado: {item.quantity}."
            )
        price = await get_adjusted_price(db, from_decimal128(product["price"]))
        oi = OrderItem(
            product_id=product["_id"],
            name=product["name"],
            quantity=item.quantity,
            price_at_purchase=price,
        )
        return oi, [
            {
                "id": ObjectId(item.product_id),
                "quantity_to_decrement": item.quantity,
                "name": product["name"],
            }
        ]

    # ── Try as a combo ──
    combo = await combos.find_one({"_id": ObjectId(item.product_id)})
    if not combo:
        raise NotFoundError(
            f"Producto o Combo con ID {item.product_id} no encontrado."
        )

    if not combo.get("active", False):
        raise ComboInactiveError(
            f"El combo '{combo['name']}' ya no está disponible. "
            f"Por favor, elimínalo de tu carrito antes de continuar."
        )

    logger.info("Processing combo '%s' (qty=%s)", combo["name"], item.quantity)

    decrement_ops: list[dict] = []
    for ci in combo.get("items", []):
        pid, qty_per = ci["product_id"], ci["quantity"]
        needed = qty_per * item.quantity

        comp = await products.find_one({"_id": ObjectId(pid)})
        if not comp:
            raise NotFoundError(f"Producto {pid} del combo no encontrado.")

        if comp.get("stock", 0) < needed:
            raise InsufficientStockError(
                f"Stock insuficiente para '{comp['name']}' "
                f"(parte del combo '{combo['name']}'). "
                f"Disponible: {comp.get('stock', 0)}, Necesario: {needed}."
            )
        decrement_ops.append(
            {
                "id": ObjectId(pid),
                "quantity_to_decrement": needed,
                "name": comp["name"],
            }
        )

    price = await get_adjusted_price(db, from_decimal128(combo["price"]))
    oi = OrderItem(
        product_id=ObjectId(item.product_id),
        name=f"{combo['name']} (Combo)",
        quantity=item.quantity,
        price_at_purchase=price,
    )
    return oi, decrement_ops
