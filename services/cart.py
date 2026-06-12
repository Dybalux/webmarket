"""Cart business logic — cart operations with stock validation.

Public API:
  - get_cart(db, user_id) -> CartDetailed
  - add_to_cart(db, user_id, product_id, quantity) -> Cart
  - update_cart_item(db, user_id, product_id, quantity) -> Cart
  - remove_from_cart(db, user_id, product_id) -> Cart
  - clear_cart(db, user_id) -> Cart
  - cleanup_cart(db, user_id) -> dict
  - validate_cart_stock(db, user_id) -> dict

All functions receive db: AsyncIOMotorDatabase, raise domain exceptions from
services.exceptions, and return Pydantic models or domain dicts.

Duplication eliminated (4 places → 2 private helpers):
  - _resolve_item_type: resolves product_id → product / combo / inactive_combo / not_found
  - _check_stock: batch stock validation for a list of {product_id, quantity}
    Used by add_to_cart, update_cart_item, and validate_cart_stock.
"""

from __future__ import annotations

import logging
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from models import Cart, CartDetailed, CartItem, CartItemDetailed
from services.exceptions import (
    CartItemNotFoundError,
    InsufficientStockError,
    NotFoundError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_or_create_cart(
    db: AsyncIOMotorDatabase, user_id: str
) -> Cart:
    """Get the user's existing cart or create an empty one."""
    carts = db["carts"]
    cart_db = await carts.find_one({"user_id": user_id})
    if cart_db:
        cart_db["_id"] = str(cart_db["_id"])
        return Cart(**cart_db)

    new_cart_data = {"user_id": user_id, "items": []}
    result = await carts.insert_one(new_cart_data)
    new_cart_data["_id"] = str(result.inserted_id)
    return Cart(**new_cart_data)


async def _save_cart(db: AsyncIOMotorDatabase, cart: Cart) -> Cart:
    """Save or update a cart document in the database."""
    carts = db["carts"]
    cart_dict = cart.model_dump(by_alias=True, exclude_unset=True)

    if cart.id:
        await carts.update_one(
            {"_id": ObjectId(cart.id)},
            {"$set": {"items": cart_dict["items"], "user_id": cart_dict["user_id"]}},
        )
    else:
        result = await carts.insert_one(cart_dict)
        cart.id = str(result.inserted_id)
    return cart


async def _resolve_item_type(
    db: AsyncIOMotorDatabase, product_id: str
) -> tuple[str, Optional[dict]]:
    """Resolve a product_id to its item type and document.

    Returns:
        ("product", doc)      — found as a regular product
        ("combo", doc)        — found as an active combo
        ("inactive_combo", doc) — found as an inactive combo
        ("not_found", None)   — neither product nor combo
    """
    products = db["products"]
    combos = db["combos"]

    product = await products.find_one({"_id": ObjectId(product_id)})
    if product:
        return ("product", product)

    combo = await combos.find_one({"_id": ObjectId(product_id)})
    if combo:
        if combo.get("active", False):
            return ("combo", combo)
        return ("inactive_combo", combo)

    return ("not_found", None)


async def _resolve_combo_components(
    db: AsyncIOMotorDatabase, combo_id: str, quantity: int
) -> list[dict]:
    """Resolve a combo to its component products with required quantities.

    Returns:
        List of dicts with keys: product_id, name, quantity_per_combo,
        total_needed, available_stock, found.
        Returns empty list if the combo is not found.
    """
    combos = db["combos"]
    products = db["products"]

    combo = await combos.find_one({"_id": ObjectId(combo_id)})
    if not combo:
        return []

    components = []
    for item in combo.get("items", []):
        product = await products.find_one(
            {"_id": ObjectId(item["product_id"])}
        )
        components.append(
            {
                "product_id": item["product_id"],
                "name": product["name"] if product else "",
                "quantity_per_combo": item["quantity"],
                "total_needed": item["quantity"] * quantity,
                "available_stock": product.get("stock", 0) if product else 0,
                "found": product is not None,
            }
        )
    return components


async def _check_stock(
    db: AsyncIOMotorDatabase, items: list[dict]
) -> list[dict]:
    """Validate stock for a batch of items.

    Args:
        items: List of {"product_id": str, "quantity": int} dicts.

    Returns:
        List of stock issues found. Empty list means all items are in stock.
        Each issue has: product_id, quantity, item_type, name, issue,
        and issue-specific fields (available, needed, component_name).
    """
    issues = []
    for item in items:
        pid = item["product_id"]
        qty = item["quantity"]

        item_type, doc = await _resolve_item_type(db, pid)

        if item_type == "product":
            stock = doc.get("stock", 0)
            if stock < qty:
                issues.append(
                    {
                        "product_id": pid,
                        "quantity": qty,
                        "item_type": "product",
                        "name": doc["name"],
                        "available": stock,
                        "issue": "insufficient_stock",
                    }
                )
        elif item_type == "combo":
            components = await _resolve_combo_components(db, pid, qty)
            for comp in components:
                if not comp["found"]:
                    issues.append(
                        {
                            "product_id": pid,
                            "combo_name": doc["name"],
                            "component_id": comp["product_id"],
                            "issue": "component_not_found",
                        }
                    )
                elif comp["available_stock"] < comp["total_needed"]:
                    issues.append(
                        {
                            "product_id": pid,
                            "quantity": qty,
                            "item_type": "combo",
                            "name": doc["name"],
                            "component_name": comp["name"],
                            "available": comp["available_stock"],
                            "needed": comp["total_needed"],
                            "issue": "insufficient_combo_stock",
                        }
                    )
        elif item_type == "not_found":
            issues.append(
                {
                    "product_id": pid,
                    "quantity": qty,
                    "item_type": "not_found",
                    "issue": "not_found",
                }
            )
    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_cart(
    db: AsyncIOMotorDatabase, user_id: str
) -> CartDetailed:
    """Get the user's cart with detailed product/combo enrichment."""
    cart = await _get_or_create_cart(db, user_id)

    if not cart.items:
        return CartDetailed(id=cart.id, user_id=cart.user_id, items=[])

    products = db["products"]
    combos = db["combos"]

    all_item_ids = [ObjectId(item.product_id) for item in cart.items]

    # Bulk query for products
    products_cursor = products.find(
        {"_id": {"$in": all_item_ids}},
        {"name": 1, "price": 1, "image_url": 1, "stock": 1},
    )
    products_dict = {str(p["_id"]): p async for p in products_cursor}

    # Bulk query for combos
    combos_cursor = combos.find(
        {"_id": {"$in": all_item_ids}},
        {"name": 1, "price": 1, "image_url": 1, "items": 1, "active": 1},
    )
    combos_dict = {str(c["_id"]): c async for c in combos_cursor}

    # Collect product IDs inside combos for a single extra query
    combo_product_ids = set()
    for combo in combos_dict.values():
        for combo_item in combo.get("items", []):
            combo_product_ids.add(ObjectId(combo_item["product_id"]))

    combo_products_dict: dict[str, dict] = {}
    if combo_product_ids:
        combo_products_cursor = products.find(
            {"_id": {"$in": list(combo_product_ids)}},
            {"name": 1, "image_url": 1},
        )
        combo_products_dict = {
            str(p["_id"]): p async for p in combo_products_cursor
        }

    enriched_items = []
    for item in cart.items:
        pid = item.product_id

        if pid in products_dict:
            product = products_dict[pid]
            enriched_items.append(
                CartItemDetailed(
                    product_id=pid,
                    quantity=item.quantity,
                    item_type="product",
                    name=product["name"],
                    price=product["price"],
                    image_url=product.get("image_url"),
                    stock=product.get("stock", 0),
                    combo_items=None,
                )
            )
        elif pid in combos_dict:
            combo = combos_dict[pid]
            combo_items_info = []
            for combo_item in combo.get("items", []):
                cpid = combo_item["product_id"]
                if cpid in combo_products_dict:
                    prod = combo_products_dict[cpid]
                    combo_items_info.append(
                        {
                            "product_id": cpid,
                            "name": prod["name"],
                            "quantity": combo_item["quantity"],
                            "image_url": prod.get("image_url"),
                        }
                    )
            enriched_items.append(
                CartItemDetailed(
                    product_id=pid,
                    quantity=item.quantity,
                    item_type="combo",
                    name=combo["name"],
                    price=combo["price"],
                    image_url=combo.get("image_url"),
                    stock=None,
                    combo_items=combo_items_info,
                )
            )
        else:
            logger.warning(
                "Item %s en carrito de usuario %s no encontrado", pid, user_id
            )

    return CartDetailed(
        id=cart.id,
        user_id=cart.user_id,
        items=enriched_items,
    )


async def add_to_cart(
    db: AsyncIOMotorDatabase,
    user_id: str,
    product_id: str,
    quantity: int,
) -> Cart:
    """Add a product or combo to the user's cart, or update its quantity.

    Raises:
        NotFoundError: When the product_id doesn't match any product or combo.
        InsufficientStockError: When stock is insufficient.
    """
    # Resolve item type (product, combo, or not found)
    item_type, item_doc = await _resolve_item_type(db, product_id)
    if item_type == "not_found":
        raise NotFoundError("Producto o combo no encontrado.")

    cart = await _get_or_create_cart(db, user_id)

    # Calculate existing quantity to compute the total after adding
    existing_quantity = 0
    for item in cart.items:
        if item.product_id == product_id:
            existing_quantity = item.quantity
            break

    total_quantity = existing_quantity + quantity

    # Validate stock via the consolidated helper
    issues = await _check_stock(
        db, [{"product_id": product_id, "quantity": total_quantity}]
    )
    if issues:
        issue = issues[0]
        if issue["issue"] == "not_found":
            raise NotFoundError("Producto o combo no encontrado.")
        elif issue["issue"] == "component_not_found":
            raise NotFoundError(
                f"Producto {issue['component_id']} del combo no encontrado."
            )
        elif issue["issue"] == "insufficient_stock":
            raise InsufficientStockError(
                f"Stock insuficiente para el producto '{issue['name']}'. "
                f"Solo quedan {issue['available']} unidades "
                f"y ya tienes {existing_quantity} en el carrito."
            )
        elif issue["issue"] == "insufficient_combo_stock":
            raise InsufficientStockError(
                f"Stock insuficiente para '{issue['component_name']}' "
                f"(parte del combo '{issue['name']}'). "
                f"Disponible: {issue['available']}, "
                f"Necesario: {issue['needed']}."
            )

    # Add or update the item
    found = False
    for item in cart.items:
        if item.product_id == product_id:
            item.quantity = total_quantity
            found = True
            break

    if not found:
        cart.items.append(CartItem(product_id=product_id, quantity=quantity))

    await _save_cart(db, cart)

    item_type_label = "combo" if item_type == "combo" else "producto"
    logger.info(
        "Usuario %s añadió/actualizó %s %s en el carrito. Cantidad total: %s",
        user_id,
        item_type_label,
        product_id,
        total_quantity,
    )
    return cart


async def update_cart_item(
    db: AsyncIOMotorDatabase,
    user_id: str,
    product_id: str,
    quantity: int,
) -> Cart:
    """Update the quantity of an item in the cart. Quantity = 0 removes it.

    Raises:
        NotFoundError: When product_id doesn't match any product or combo.
        CartItemNotFoundError: When the item is not in the user's cart.
        InsufficientStockError: When stock is insufficient for the new quantity.
    """
    # Validate stock only when increasing quantity (quantity > 0)
    if quantity > 0:
        item_type, item_doc = await _resolve_item_type(db, product_id)
        if item_type == "not_found":
            raise NotFoundError("Producto o combo no encontrado.")

        issues = await _check_stock(
            db, [{"product_id": product_id, "quantity": quantity}]
        )
        if issues:
            issue = issues[0]
            if issue["issue"] == "not_found":
                raise NotFoundError("Producto o combo no encontrado.")
            elif issue["issue"] == "component_not_found":
                raise NotFoundError(
                    f"Producto {issue['component_id']} del combo no encontrado."
                )
            elif issue["issue"] == "insufficient_stock":
                raise InsufficientStockError(
                    f"Stock insuficiente para el producto '{issue['name']}'. "
                    f"Solo quedan {issue['available']} unidades."
                )
            elif issue["issue"] == "insufficient_combo_stock":
                raise InsufficientStockError(
                    f"Stock insuficiente para '{issue['component_name']}' "
                    f"(parte del combo '{issue['name']}'). "
                    f"Disponible: {issue['available']}, "
                    f"Necesario: {issue['needed']}."
                )

    cart = await _get_or_create_cart(db, user_id)

    # Update quantity or remove
    found = False
    updated_items = []
    for item in cart.items:
        if item.product_id == product_id:
            found = True
            if quantity > 0:
                item.quantity = quantity
                updated_items.append(item)
            # quantity == 0: skip (item removed)
        else:
            updated_items.append(item)

    if not found:
        raise CartItemNotFoundError(
            "El producto/combo no está en el carrito."
        )

    cart.items = updated_items
    await _save_cart(db, cart)
    logger.info(
        "Usuario %s actualizó cantidad de item %s a %s en el carrito.",
        user_id,
        product_id,
        quantity,
    )
    return cart


async def remove_from_cart(
    db: AsyncIOMotorDatabase, user_id: str, product_id: str
) -> Cart:
    """Remove an item from the user's cart.

    Raises:
        CartItemNotFoundError: When the item is not in the cart.
    """
    cart = await _get_or_create_cart(db, user_id)

    original_count = len(cart.items)
    cart.items = [
        item for item in cart.items if item.product_id != product_id
    ]

    if len(cart.items) == original_count:
        raise CartItemNotFoundError("El producto no está en el carrito.")

    await _save_cart(db, cart)
    logger.info(
        "Usuario %s eliminó producto %s del carrito.", user_id, product_id
    )
    return cart


async def clear_cart(
    db: AsyncIOMotorDatabase, user_id: str
) -> Cart:
    """Clear all items from the user's cart."""
    cart = await _get_or_create_cart(db, user_id)
    cart.items = []
    await _save_cart(db, cart)
    logger.info("Usuario %s ha vaciado su carrito.", user_id)
    return cart


async def cleanup_cart(
    db: AsyncIOMotorDatabase, user_id: str
) -> dict:
    """Remove invalid items from the cart (deleted products, inactive combos).

    Returns:
        {"cart": Cart, "removed_items": list[dict], "removed_count": int}
    """
    cart = await _get_or_create_cart(db, user_id)

    valid_items = []
    removed_items = []

    for item in cart.items:
        item_type, doc = await _resolve_item_type(db, item.product_id)

        if item_type == "product":
            valid_items.append(item)
        elif item_type == "combo":
            valid_items.append(item)
        elif item_type == "inactive_combo":
            removed_items.append(
                {
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "reason": f"Combo desactivado: {doc['name']}",
                }
            )
            logger.info(
                "Removido combo desactivado %s del carrito de usuario %s",
                item.product_id,
                user_id,
            )
        else:  # not_found
            removed_items.append(
                {
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "reason": "Producto o combo no encontrado",
                }
            )
            logger.info(
                "Removido item inexistente %s del carrito de usuario %s",
                item.product_id,
                user_id,
            )

    cart.items = valid_items
    await _save_cart(db, cart)

    return {
        "cart": cart,
        "removed_items": removed_items,
        "removed_count": len(removed_items),
    }


async def validate_cart_stock(
    db: AsyncIOMotorDatabase, user_id: str
) -> dict:
    """Validate stock for all items in the cart without modifying it.

    Returns:
        {"items": list[dict], "all_available": bool}
    """
    cart = await _get_or_create_cart(db, user_id)
    products = db["products"]

    validation_results = []

    for item in cart.items:
        item_type, doc = await _resolve_item_type(db, item.product_id)

        if item_type == "product":
            available = doc.get("stock", 0) >= item.quantity
            validation_results.append(
                {
                    "product_id": item.product_id,
                    "quantity_in_cart": item.quantity,
                    "available": available,
                    "stock": doc.get("stock", 0),
                    "item_type": "product",
                    "name": doc["name"],
                }
            )
        elif item_type in ("combo", "inactive_combo"):
            available = True
            limiting_product = None

            for combo_item in doc.get("items", []):
                prod = await products.find_one(
                    {"_id": ObjectId(combo_item["product_id"])}
                )
                if prod:
                    needed = combo_item["quantity"] * item.quantity
                    stock = prod.get("stock", 0)
                    if stock < needed:
                        available = False
                        limiting_product = {
                            "name": prod["name"],
                            "stock": stock,
                            "needed": needed,
                        }
                        break

            result = {
                "product_id": item.product_id,
                "quantity_in_cart": item.quantity,
                "available": available,
                "item_type": "combo",
                "name": doc["name"],
                "active": doc.get("active", False),
            }
            if limiting_product:
                result["limiting_product"] = limiting_product
            validation_results.append(result)
        else:
            # not_found
            validation_results.append(
                {
                    "product_id": item.product_id,
                    "quantity_in_cart": item.quantity,
                    "available": False,
                    "item_type": "unknown",
                    "name": "Item no encontrado",
                    "error": "Producto o combo no existe",
                }
            )

    return {
        "items": validation_results,
        "all_available": all(
            item["available"] for item in validation_results
        ),
    }
