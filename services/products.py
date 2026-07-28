"""Products business logic — CRUD, listing, and pricing enrichment.

Public API (see design §2.8):
  - create_product(db, product_data, admin_user_id) -> AdminProduct
  - list_products(db, skip, limit, filters) -> dict {items, meta}
  - get_product(db, product_id) -> Product
  - update_product(db, product_id, update_data, admin_user_id) -> AdminProduct
  - delete_product(db, product_id, admin_user_id) -> None
  - toggle_product_active(db, product_id, admin_user_id) -> AdminProduct

All functions receive db: AsyncIOMotorDatabase, raise domain exceptions from
services.exceptions, and return Pydantic models or domain dicts.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from models import AdminProduct, PaginationMeta, Product, ProductCategory, ProductUpdate
from services.exceptions import (
    DuplicateProductNameError,
    InternalError,
    NotFoundError,
)
from services.pricing import get_adjusted_price
from utils.money import decimalize_doc, from_decimal128, quantize_money
from utils.sanitize import escape_regex

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API — admin CRUD
# ---------------------------------------------------------------------------


async def create_product(
    db: AsyncIOMotorDatabase,
    product_data: AdminProduct,
    admin_user_id: str,
) -> AdminProduct:
    """Create a new product in the catalog.

    Raises:
        DuplicateProductNameError: when a product with the same name exists.
        InternalError: when the insert or post-insert fetch fails.
    """
    products = db["products"]

    # Check for duplicate name
    existing = await products.find_one({"name": product_data.name})
    if existing:
        raise DuplicateProductNameError("El nombre del producto ya existe.")

    product_dict = product_data.model_dump(
        exclude_unset=True,
        exclude={"id"},
        by_alias=True,
    )
    result = await products.insert_one(decimalize_doc(product_dict))

    if not result.inserted_id:
        raise InternalError("No se pudo crear el producto.")

    created = await products.find_one({"_id": result.inserted_id})
    if created:
        return AdminProduct.model_validate(created)

    raise InternalError("Producto creado pero no se pudo recuperar.")


async def list_products(
    db: AsyncIOMotorDatabase,
    skip: int,
    limit: int,
    *,
    category: Optional[ProductCategory] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    search: Optional[str] = None,
    include_out_of_stock: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Return a paginated product listing with optional filters and dynamic pricing.

    Returns a dict with ``items`` (list of Product) and ``meta`` (PaginationMeta).
    """
    products = db["products"]
    query: dict = {"active": True}

    if not include_out_of_stock:
        query["stock"] = {"$gt": 0}

    if category:
        query["category"] = category.value

    if min_price is not None:
        query["price"] = {"$gte": min_price}

    if max_price is not None:
        if "price" in query:
            query["price"]["$lte"] = max_price
        else:
            query["price"] = {"$lte": max_price}

    if search:
        safe_search = escape_regex(search)
        query["$or"] = [
            {"name": {"$regex": safe_search, "$options": "i"}},
            {"description": {"$regex": safe_search, "$options": "i"}},
        ]

    total = await products.count_documents(query)
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    cursor = products.find(query).skip(skip).limit(limit)
    items: list[Product] = []
    async for doc in cursor:
        product = Product(**doc)
        product.price = await get_adjusted_price(db, product.price)
        items.append(product)

    meta = PaginationMeta(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )

    return {"items": items, "meta": meta}


async def get_product(
    db: AsyncIOMotorDatabase,
    product_id: str,
) -> Product:
    """Return a single active product with dynamic pricing applied.

    Raises:
        NotFoundError: when the product is not found or is inactive.
    """
    products = db["products"]

    product_db = await products.find_one(
        {"_id": ObjectId(product_id), "active": True}
    )
    if not product_db:
        raise NotFoundError("Producto no encontrado.")

    product = Product(**product_db)
    product.price = await get_adjusted_price(db, product.price)
    return product


async def update_product(
    db: AsyncIOMotorDatabase,
    product_id: str,
    update_data: ProductUpdate,
    admin_user_id: str,
) -> AdminProduct:
    """Update an existing product, with optional profit-percentage price calc.

    Raises:
        NotFoundError: when the product does not exist.
    """
    products = db["products"]

    current = await products.find_one({"_id": ObjectId(product_id)})
    if not current:
        raise NotFoundError("Producto no encontrado.")

    data = update_data.model_dump(exclude_unset=True)

    # Profit-percentage price calculation
    if "profit_percentage" in data:
        profit_pct = data.pop("profit_percentage")
        net_price = data.get("net_price")
        if net_price is None:
            net_price = current.get("net_price")
        if net_price is not None:
            net_price_dec = from_decimal128(net_price)
            calculated = quantize_money(
                net_price_dec * (1 + Decimal(str(profit_pct)) / 100)
            )
            data["price"] = calculated
            logger.info(
                "Precio calculado automáticamente: %s (Neto: %s, Ganancia: %.1f%%)",
                calculated,
                net_price_dec,
                profit_pct,
            )
        else:
            logger.warning(
                "No se pudo calcular el precio para %s porque falta 'net_price'",
                product_id,
            )

    # Prevent changing the document ID
    for key in ("_id", "id"):
        data.pop(key, None)

    if not data:
        return AdminProduct(**current)

    await products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": decimalize_doc(data)},
    )

    updated = await products.find_one({"_id": ObjectId(product_id)})
    return AdminProduct(**updated)


async def delete_product(
    db: AsyncIOMotorDatabase,
    product_id: str,
    admin_user_id: str,
) -> None:
    """Delete a product from the catalog.

    Does NOT return a value (caller sends 204).

    Raises:
        NotFoundError: when the product does not exist.
    """
    products = db["products"]

    result = await products.delete_one({"_id": ObjectId(product_id)})

    if result.deleted_count == 0:
        raise NotFoundError("Producto no encontrado para eliminar.")


async def toggle_product_active(
    db: AsyncIOMotorDatabase,
    product_id: str,
    admin_user_id: str,
) -> AdminProduct:
    """Toggle the active flag of a product (soft delete / restore).

    Raises:
        NotFoundError: when the product does not exist.
    """
    products = db["products"]

    product = await products.find_one({"_id": ObjectId(product_id)})
    if not product:
        raise NotFoundError("Producto no encontrado.")

    new_state = not product.get("active", True)

    await products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"active": new_state}},
    )

    updated = await products.find_one({"_id": ObjectId(product_id)})
    return AdminProduct(**updated)
