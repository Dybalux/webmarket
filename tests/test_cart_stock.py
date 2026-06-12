"""Endpoint tests for the cart and products HTTP surface.

These tests cover the cart stock validation endpoint and an
endpoint-layer mirror of the products out-of-stock filter.

Tasks covered
-------------
T3.6  GET /cart/validate-stock
        * All items in stock → all_available=true
        * One item insufficient → all_available=false
T3.7  GET /products (endpoint layer complement to T2.7)
        * Default filter hides zero-stock
        * include_out_of_stock=true includes zero-stock (admin)

The cart tests mount the cart router on the minimal test app. The
products tests mount the products router. The pricing_settings
override is no longer needed — the refactored products router uses
services.pricing.get_adjusted_price which reads from db through
the already-overridden get_database dependency.

All tests are marked @pytest.mark.endpoint. Production code is
untouched.

Technical notes
---------------
* The cart router is mounted at "/", so the path is "/validate-stock".
  It does NOT require the get_current_admin_user dep, but the
  conftest auth_user_dep fixture applies that override anyway —
  harmless for the cart endpoints.
* The cart router's `validate_cart_stock` reads from the user's cart
  (keyed by user_id) and returns a list of items with
  {product_id, quantity_in_cart, available, stock, item_type, name}
  plus a top-level `all_available` boolean.
* The products router returns a paginated envelope: `{"items": [...],
  "meta": {...}}`. The endpoint-layer tests use the same shape as
  the T2.7 tests but verify query param routing.
"""

from __future__ import annotations

import pytest
from bson import ObjectId
from fastapi import FastAPI

from routers import cart as cart_router
from routers import products as products_router
from tests.conftest import FAKE_USER_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mount_cart_and_app(test_app: FastAPI) -> None:
    """Mount the cart router on the test app."""
    test_app.include_router(cart_router.router)


def _mount_products_app(test_app: FastAPI) -> None:
    """Mount the products router on the test app.

    No pricing_settings override needed — the refactored router uses
    services.pricing.get_adjusted_price which reads directly from
    the already-overridden get_database dependency.
    """
    test_app.include_router(products_router.router)


def _apply_user_overrides(test_app: FastAPI, auth_user_dep) -> None:
    for dep, override in auth_user_dep.items():
        test_app.dependency_overrides[dep] = override


def _apply_admin_overrides(test_app: FastAPI, auth_admin_dep) -> None:
    for dep, override in auth_admin_dep.items():
        test_app.dependency_overrides[dep] = override


# ---------------------------------------------------------------------------
# T3.6 — GET /cart/validate-stock
# ---------------------------------------------------------------------------


class TestCartValidateStock:
    @pytest.mark.endpoint
    async def test_all_items_in_stock_returns_all_available_true(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """Cart with 2 products, both with sufficient stock → all_available=true.

        The response shape per the cart router source:
            {
                "items": [
                    {
                        "product_id": str,
                        "quantity_in_cart": int,
                        "available": true,
                        "stock": int,
                        "item_type": "product",
                        "name": str,
                    },
                    ...
                ],
                "all_available": true,
            }
        """
        products = test_db["products"]
        carts = test_db["carts"]

        quilmes = await products.find_one({"name": "Quilmes 1L"})
        malbec = await products.find_one({"name": "Vino Malbec 750ml"})
        # Pre-condition: both have plenty of stock.
        assert quilmes["stock"] == 20
        assert malbec["stock"] == 12

        await carts.insert_one(
            {
                "_id": ObjectId(),
                "user_id": FAKE_USER_ID,
                "items": [
                    {"product_id": str(quilmes["_id"]), "quantity": 2},
                    {"product_id": str(malbec["_id"]), "quantity": 3},
                ],
            }
        )

        _mount_cart_and_app(test_app)
        _apply_user_overrides(test_app, auth_user_dep)

        response = await test_client.get("/validate-stock")
        assert response.status_code == 200, response.text
        body = response.json()

        # Spec: top-level all_available must be true.
        assert body["all_available"] is True

        # Spec: per-item, each must report available=true with the
        # actual current stock.
        items = body["items"]
        assert len(items) == 2

        by_id = {item["product_id"]: item for item in items}
        q = by_id[str(quilmes["_id"])]
        m = by_id[str(malbec["_id"])]

        assert q["available"] is True
        assert q["stock"] == 20
        assert q["quantity_in_cart"] == 2
        assert q["item_type"] == "product"
        assert q["name"] == "Quilmes 1L"

        assert m["available"] is True
        assert m["stock"] == 12
        assert m["quantity_in_cart"] == 3
        assert m["item_type"] == "product"
        assert m["name"] == "Vino Malbec 750ml"

    @pytest.mark.endpoint
    async def test_one_item_insufficient_returns_all_available_false(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """Cart with 2 products, one with insufficient stock →
        all_available=false and the insufficient item reports
        available=false with the available stock count.
        """
        products = test_db["products"]
        carts = test_db["carts"]

        # Drop Stella to stock=2 and ask for 5.
        stella = await products.find_one({"name": "Stella Artois 1L"})
        await products.update_one(
            {"_id": stella["_id"]}, {"$set": {"stock": 2}}
        )
        # Quilmes has plenty of stock.
        quilmes = await products.find_one({"name": "Quilmes 1L"})

        await carts.insert_one(
            {
                "_id": ObjectId(),
                "user_id": FAKE_USER_ID,
                "items": [
                    {"product_id": str(quilmes["_id"]), "quantity": 1},
                    {"product_id": str(stella["_id"]), "quantity": 5},
                ],
            }
        )

        _mount_cart_and_app(test_app)
        _apply_user_overrides(test_app, auth_user_dep)

        response = await test_client.get("/validate-stock")
        assert response.status_code == 200, response.text
        body = response.json()

        # Spec: top-level all_available must be false.
        assert body["all_available"] is False

        items = body["items"]
        assert len(items) == 2
        by_id = {item["product_id"]: item for item in items}

        # The Quilmes item must be available.
        q = by_id[str(quilmes["_id"])]
        assert q["available"] is True
        assert q["stock"] == 20
        assert q["quantity_in_cart"] == 1

        # The Stella item must NOT be available, and the report must
        # include the available stock (2) so the UI can show "only 2 left".
        s = by_id[str(stella["_id"])]
        assert s["available"] is False
        assert s["stock"] == 2
        assert s["quantity_in_cart"] == 5


# ---------------------------------------------------------------------------
# T3.7 — GET /products (endpoint complement to T2.7)
# ---------------------------------------------------------------------------


class TestProductsEndpointRouting:
    @pytest.mark.endpoint
    async def test_default_endpoint_hides_zero_stock(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """Endpoint-layer mirror of T2.7a: GET /products/ (no params)
        must exclude the stock=0 SKU (Fernet Branca) and include the
        in-stock ones.
        """
        _mount_products_app(test_app)
        _apply_user_overrides(test_app, auth_user_dep)

        response = await test_client.get("/")
        assert response.status_code == 200, response.text
        body = response.json()
        names = [p["name"] for p in body["items"]]

        assert "Fernet Branca 750ml" not in names
        for expected in ("Quilmes 1L", "Stella Artois 1L", "Vino Malbec 750ml"):
            assert expected in names

    @pytest.mark.endpoint
    async def test_admin_include_out_of_stock_query_param(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """Endpoint-layer mirror of T2.7b: GET /products/?include_out_of_stock=true
        must include the zero-stock SKU.
        """
        _mount_products_app(test_app)
        _apply_admin_overrides(test_app, auth_admin_dep)

        response = await test_client.get("/?include_out_of_stock=true")
        assert response.status_code == 200, response.text
        body = response.json()
        names = [p["name"] for p in body["items"]]

        assert "Fernet Branca 750ml" in names
        # Total count is the seeded 4 products.
        assert body["meta"]["total"] == 4
