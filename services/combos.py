"""Combo business logic — CRUD, enrichment, pricing, and savings calculation.

Public API (see design §2.4):
  - list_active_combos  → all active combos with enrichment + dynamic pricing
  - get_combo_by_id     → single active combo with dynamic pricing
  - list_all_combos     → admin: all combos with enrichment (base prices)
  - create_combo        → admin: validate product refs and create
  - update_combo        → admin: validate and update
  - delete_combo        → admin: soft-deactivate or hard-delete

All functions receive ``db: AsyncIOMotorDatabase``, raise domain exceptions from
``services.exceptions``, and return Pydantic models or domain dicts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Set

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from models import Combo, ComboCreate, ComboDetailed, ComboItemDetailed, ComboUpdate
from services.exceptions import InternalError, NotFoundError, ValidationError
from services.pricing import get_adjusted_price

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers — enrichment pipeline (shared by public + admin endpoints)
# ---------------------------------------------------------------------------


async def _bulk_load_products(
    db: AsyncIOMotorDatabase,
    product_ids: Set[ObjectId],
) -> dict:
    """Fetch multiple products by ObjectId in a single query.

    Returns a ``{str(_id): product_doc}`` dict for O(1) lookup during
    enrichment.
    """
    if not product_ids:
        return {}
    cursor = db["products"].find(
        {"_id": {"$in": list(product_ids)}},
        {"name": 1, "price": 1, "image_url": 1, "stock": 1},
    )
    return {str(p["_id"]): p async for p in cursor}


async def _enrich_combos(
    db: AsyncIOMotorDatabase,
    combos_list: list[dict],
    *,
    apply_dynamic_pricing: bool = True,
) -> list[ComboDetailed]:
    """Enrich raw combo documents with product details, pricing, and savings.

    Shared by ``list_active_combos`` (with dynamic pricing) and
    ``list_all_combos`` (admin view, base prices only).  The savings
    calculation is the canonical one from ``routers/combos.py:87-89``::

        savings = sum(component_prices * quantities) - combo_price
    """
    if not combos_list:
        return []

    # ── Collect all unique product IDs across every combo ──
    all_product_ids: set[ObjectId] = set()
    for combo_doc in combos_list:
        for item in combo_doc.get("items", []):
            pid = item["product_id"]
            if isinstance(pid, str):
                all_product_ids.add(ObjectId(pid))
            else:
                all_product_ids.add(pid)

    # ── Single bulk query for every referenced product ──
    products_dict = await _bulk_load_products(db, all_product_ids)

    # ── Build enriched response ──
    enriched: list[ComboDetailed] = []
    for combo_doc in combos_list:
        enriched_items: list[ComboItemDetailed] = []

        for item in combo_doc.get("items", []):
            pid_str = str(item["product_id"])
            if pid_str in products_dict:
                prod = products_dict[pid_str]
                enriched_items.append(
                    ComboItemDetailed(
                        product_id=pid_str,
                        quantity=item["quantity"],
                        name=prod["name"],
                        price=prod["price"],
                        image_url=prod.get("image_url"),
                        stock=prod.get("stock", 0),
                    )
                )
            else:
                logger.warning(
                    "Producto %s del combo %s no encontrado",
                    pid_str,
                    combo_doc["_id"],
                )

        # Savings = sum(component unit price × combo quantity) − combo price
        total_items_cost = sum(
            ei.price * ei.quantity for ei in enriched_items
        )

        combo_price = combo_doc["price"]
        if apply_dynamic_pricing:
            combo_price = await get_adjusted_price(db, combo_price)

        savings = round(total_items_cost - combo_price, 2)

        enriched.append(
            ComboDetailed(
                _id=combo_doc["_id"],
                name=combo_doc["name"],
                description=combo_doc.get("description"),
                price=combo_price,
                image_url=combo_doc.get("image_url"),
                items=enriched_items,
                active=combo_doc.get("active", True),
                created_at=combo_doc.get("created_at"),
                updated_at=combo_doc.get("updated_at"),
                total_items_cost=round(total_items_cost, 2),
                savings=savings,
            )
        )

    return enriched


# ---------------------------------------------------------------------------
# Public API — public endpoints
# ---------------------------------------------------------------------------


async def list_active_combos(
    db: AsyncIOMotorDatabase,
) -> list[ComboDetailed]:
    """Return all active combos with full product enrichment and dynamic pricing.

    Replicates ``GET /combos`` from ``routers/combos.py``.
    """
    combos_list = await db["combos"].find({"active": True}) \
        .sort("created_at", -1) \
        .to_list(length=None)

    result = await _enrich_combos(db, combos_list, apply_dynamic_pricing=True)
    logger.info(
        "Se obtuvieron %d combos activos con información detallada.",
        len(result),
    )
    return result


async def get_combo_by_id(
    db: AsyncIOMotorDatabase,
    combo_id: str,
) -> Combo:
    """Return a single active combo by ID with dynamic pricing applied.

    Raises:
        NotFoundError: when the combo is not found or is inactive.

    Replicates ``GET /combos/{id}`` from ``routers/combos.py``.
    """
    combo_doc = await db["combos"].find_one(
        {"_id": ObjectId(combo_id), "active": True}
    )
    if not combo_doc:
        raise NotFoundError("Combo no encontrado.")

    combo = Combo(**combo_doc)
    combo.price = await get_adjusted_price(db, combo.price)
    return combo


# ---------------------------------------------------------------------------
# Public API — admin endpoints
# ---------------------------------------------------------------------------


async def list_all_combos(
    db: AsyncIOMotorDatabase,
    include_inactive: bool = False,
) -> list[ComboDetailed]:
    """Return all combos (admin view) with product enrichment.

    Admin view does **not** apply dynamic pricing — uses stored base prices
    and calculates savings against them.

    Replicates ``GET /combos/admin/all`` from ``routers/combos.py``.
    """
    query = {} if include_inactive else {"active": True}
    combos_list = await db["combos"].find(query) \
        .sort("created_at", -1) \
        .to_list(length=None)

    return await _enrich_combos(db, combos_list, apply_dynamic_pricing=False)


async def create_combo(
    db: AsyncIOMotorDatabase,
    combo_data: ComboCreate,
    admin_user_id: str,
) -> Combo:
    """Create a new combo after validating all referenced product IDs exist.

    Raises:
        ValidationError: when a referenced product ID is invalid.
        NotFoundError: when a referenced product does not exist in the catalog.
        InternalError: when the DB insert or post-insert fetch fails.

    Replicates ``POST /combos/admin`` from ``routers/combos.py``.
    """
    # Validate every referenced product exists
    for item in combo_data.items:
        if not ObjectId.is_valid(item.product_id):
            raise ValidationError(
                f"ID de producto inválido: {item.product_id}"
            )
        product = await db["products"].find_one(
            {"_id": ObjectId(item.product_id)}
        )
        if not product:
            raise NotFoundError(
                f"Producto con ID {item.product_id} no encontrado."
            )

    new_combo = Combo(**combo_data.model_dump())
    combo_dict = new_combo.model_dump(exclude={"_id"}, by_alias=False)

    result = await db["combos"].insert_one(combo_dict)
    if not result.inserted_id:
        raise InternalError("No se pudo crear el combo.")

    created = await db["combos"].find_one({"_id": result.inserted_id})
    logger.info(
        "Admin %s creó el combo '%s' (ID: %s).",
        admin_user_id,
        combo_data.name,
        result.inserted_id,
    )
    return Combo(**created)


async def update_combo(
    db: AsyncIOMotorDatabase,
    combo_id: str,
    update_data: ComboUpdate,
    admin_user_id: str,
) -> Combo:
    """Update an existing combo.  Re-validates product references when items
    are changed.

    Raises:
        NotFoundError: when the combo or a referenced product is not found.
        ValidationError: when a referenced product ID is invalid.

    Replicates ``PUT /combos/admin/{id}`` from ``routers/combos.py``.
    """
    combo_doc = await db["combos"].find_one({"_id": ObjectId(combo_id)})
    if not combo_doc:
        raise NotFoundError("Combo no encontrado.")

    # Validate product references if items are being updated
    if update_data.items:
        for item in update_data.items:
            if not ObjectId.is_valid(item.product_id):
                raise ValidationError(
                    f"ID de producto inválido: {item.product_id}"
                )
            product = await db["products"].find_one(
                {"_id": ObjectId(item.product_id)}
            )
            if not product:
                raise NotFoundError(
                    f"Producto con ID {item.product_id} no encontrado."
                )

    update_dict = update_data.model_dump(exclude_unset=True)
    update_dict["updated_at"] = datetime.now(tz=timezone.utc)

    await db["combos"].update_one(
        {"_id": ObjectId(combo_id)},
        {"$set": update_dict},
    )

    updated = await db["combos"].find_one({"_id": ObjectId(combo_id)})
    logger.info(
        "Admin %s actualizó el combo %s.",
        admin_user_id,
        combo_id,
    )
    return Combo(**updated)


async def delete_combo(
    db: AsyncIOMotorDatabase,
    combo_id: str,
    permanent: bool,
    admin_user_id: str,
) -> dict:
    """Delete or deactivate a combo.

    By default performs a soft delete (sets ``active=False``).  Use
    ``permanent=True`` for physical removal.

    Raises:
        NotFoundError: when the combo does not exist.

    Replicates ``DELETE /combos/admin/{id}`` from ``routers/combos.py``.
    """
    combo_doc = await db["combos"].find_one({"_id": ObjectId(combo_id)})
    if not combo_doc:
        raise NotFoundError("Combo no encontrado.")

    if permanent:
        await db["combos"].delete_one({"_id": ObjectId(combo_id)})
        logger.info(
            "Admin %s eliminó permanentemente el combo %s.",
            admin_user_id,
            combo_id,
        )
        return {"message": "Combo eliminado permanentemente."}
    else:
        await db["combos"].update_one(
            {"_id": ObjectId(combo_id)},
            {
                "$set": {
                    "active": False,
                    "updated_at": datetime.now(tz=timezone.utc),
                }
            },
        )
        logger.info(
            "Admin %s desactivó el combo %s.",
            admin_user_id,
            combo_id,
        )
        return {"message": "Combo desactivado correctamente."}
