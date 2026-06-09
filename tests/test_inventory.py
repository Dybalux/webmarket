"""Integration tests for the stock-decrement surface on POST /orders.

These tests mount the orders router on the minimal test app and hit
POST /orders via httpx. The in-memory mongomock-motor backend (built
by conftest) is the source of truth for product stock and the carts
collection.

  T2.1 — single-item order decrements product stock by 1
  T2.2 — three-item order decrements all three product stocks
  T2.3 — combo order decrements each component product's stock
  T2.4 — insufficient stock returns HTTP 409 with product name and
          available/requested numbers; stock is unchanged

T2.1–T2.3 were previously marked xfail due to the race condition
in create_order (separate stock check and $inc decrement). Fixed:
the $inc now uses a $gte guard to detect concurrent modifications.
check and decrement) that is out of scope for this change. The
follow-up fix-stock-bugs change will make these pass.

T2.4 is NOT xfail: the pre-check at the top of the order loop
(lines 265-269 of routers/orders.py) returns 409 cleanly.

All tests marked @pytest.mark.integration. Production code untouched.

Key technical notes:
    * The orders router's `create_order` uses a non-transactional
      $inc loop (the transactional block in routers/orders.py is
      commented out for MongoDB Atlas M0). We test that path.
    * mongomock-motor 0.0.36 supports the same find/update API as
      motor for our purposes (no session kwarg threaded through).
    * The test_app fixture already overrides get_database /
      get_collection to return the in-memory database; we just
      include the orders router on top.
"""

from __future__ import annotations

import pytest
from bson import ObjectId
from fastapi import FastAPI
from httpx import AsyncClient

from routers import orders as orders_router
from routers import pricing_settings as pricing_settings_router
from tests.conftest import FAKE_USER_ID
from models import Address


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_ADDRESS = Address(
    street="Av. San Martín 123",
    city="Santa María",
    state="Catamarca",
    zip_code="4139",
    country="Argentina",
)


def _mount_orders_and_app(test_app: FastAPI) -> None:
    """Mount the orders router (and pricing-settings as a sibling dep)."""
    test_app.include_router(orders_router.router)
    test_app.include_router(pricing_settings_router.router)


def _build_order_payload(items: list[dict]) -> dict:
    """Build a JSON-serializable OrderCreate body for POST /orders/."""
    return {
        "items": items,
        "shipping_address": VALID_ADDRESS.model_dump(),
        "shipping_zone": "pickup",  # pickup is always free, no shipping math noise
    }


# ---------------------------------------------------------------------------
# T2.1 — Stock decrement on order (single product)
# ---------------------------------------------------------------------------


class TestOrderDecrementsStock:
    @pytest.mark.integration
    async def test_order_decrements_stock(self, test_app, test_db, test_client, auth_user_dep):
        """A successful order of 1 unit must drop product stock by exactly 1.

        The orders router writes the order THEN decrements stock; for the
        test to assert stock=4 it must complete without the race-condition
        bug. Marked xfail — see fix-stock-bugs.
        """
        products = test_db["products"]
        carts = test_db["carts"]

        # Pick the Stella product (stock=5 per SAMPLE_PRODUCTS) and seed a cart.
        stella = await products.find_one({"name": "Stella Artois 1L"})
        assert stella["stock"] == 5
        await carts.insert_one(
            {
                "_id": ObjectId(),
                "user_id": FAKE_USER_ID,
                "items": [{"product_id": str(stella["_id"]), "quantity": 1}],
            }
        )

        # Mount router and apply user auth overrides.
        _mount_orders_and_app(test_app)
        for dep, override in auth_user_dep.items():
            test_app.dependency_overrides[dep] = override

        # POST /orders/ (the router exposes @router.post("/") so the path is "/")
        response = await test_client.post(
            "/",
            json=_build_order_payload(
                [{"product_id": str(stella["_id"]), "quantity": 1}]
            ),
        )

        # 201 created; response body must include the line item.
        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Stella Artois 1L"

        # Product stock must be 4.
        after = await products.find_one({"_id": stella["_id"]})
        assert after["stock"] == 4


# ---------------------------------------------------------------------------
# T2.2 — Multi-item decrement
# ---------------------------------------------------------------------------


class TestMultiItemDecrement:
    @pytest.mark.integration
    async def test_multi_item_order_decrements_all_stocks(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """Three products, one unit each → all three stocks drop by 1, order has 3 lines."""
        products = test_db["products"]
        carts = test_db["carts"]

        # Use the three high-stock SKUs: Quilmes (20), Stella (5), Malbec (12).
        quilmes = await products.find_one({"name": "Quilmes 1L"})
        stella = await products.find_one({"name": "Stella Artois 1L"})
        malbec = await products.find_one({"name": "Vino Malbec 750ml"})

        await carts.insert_one(
            {
                "_id": ObjectId(),
                "user_id": FAKE_USER_ID,
                "items": [
                    {"product_id": str(quilmes["_id"]), "quantity": 1},
                    {"product_id": str(stella["_id"]), "quantity": 1},
                    {"product_id": str(malbec["_id"]), "quantity": 1},
                ],
            }
        )

        _mount_orders_and_app(test_app)
        for dep, override in auth_user_dep.items():
            test_app.dependency_overrides[dep] = override

        response = await test_client.post(
            "/",
            json=_build_order_payload(
                [
                    {"product_id": str(quilmes["_id"]), "quantity": 1},
                    {"product_id": str(stella["_id"]), "quantity": 1},
                    {"product_id": str(malbec["_id"]), "quantity": 1},
                ]
            ),
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body["items"]) == 3

        # Each product must be decremented by exactly 1.
        after_q = await products.find_one({"_id": quilmes["_id"]})
        after_s = await products.find_one({"_id": stella["_id"]})
        after_m = await products.find_one({"_id": malbec["_id"]})
        assert after_q["stock"] == 19
        assert after_s["stock"] == 4
        assert after_m["stock"] == 11


# ---------------------------------------------------------------------------
# T2.3 — Combo decrement
# ---------------------------------------------------------------------------


class TestComboDecrement:
    @pytest.mark.integration
    async def test_combo_order_decrements_each_component(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """A combo with two products, each stock=5, ordered qty=1 → both stocks=4."""
        products = test_db["products"]
        combos = test_db["combos"]
        carts = test_db["carts"]

        stella = await products.find_one({"name": "Stella Artois 1L"})
        malbec = await products.find_one({"name": "Vino Malbec 750ml"})

        combo_id = ObjectId()
        await combos.insert_one(
            {
                "_id": combo_id,
                "name": "Pack Cata",
                "description": "Stella + Malbec",
                "price": 5000.0,
                "items": [
                    {"product_id": str(stella["_id"]), "quantity": 1},
                    {"product_id": str(malbec["_id"]), "quantity": 1},
                ],
                "active": True,
            }
        )

        await carts.insert_one(
            {
                "_id": ObjectId(),
                "user_id": FAKE_USER_ID,
                "items": [{"product_id": str(combo_id), "quantity": 1}],
            }
        )

        _mount_orders_and_app(test_app)
        for dep, override in auth_user_dep.items():
            test_app.dependency_overrides[dep] = override

        response = await test_client.post(
            "/",
            json=_build_order_payload(
                [{"product_id": str(combo_id), "quantity": 1}]
            ),
        )

        assert response.status_code == 201, response.text
        body = response.json()
        # The combo must appear as ONE order line, with the (Combo) suffix.
        assert len(body["items"]) == 1
        assert "Combo" in body["items"][0]["name"]

        # Both component products must be decremented by 1.
        after_s = await products.find_one({"_id": stella["_id"]})
        after_m = await products.find_one({"_id": malbec["_id"]})
        assert after_s["stock"] == 4
        assert after_m["stock"] == 11


# ---------------------------------------------------------------------------
# T2.4 — Stock validation 409
# ---------------------------------------------------------------------------


class TestStockValidation409:
    @pytest.mark.integration
    async def test_insufficient_stock_returns_409(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """Product stock=2, request quantity=5 → HTTP 409, body identifies product, stock unchanged.

        This test does NOT exercise the race-condition path. The orders
        router has an explicit pre-check (line 265-269) that raises 409
        before decrementing stock, so this should pass cleanly.
        """
        products = test_db["products"]
        carts = test_db["carts"]

        # Stella is seeded with stock=5. Drop it to 2 for this test.
        stella = await products.find_one({"name": "Stella Artois 1L"})
        await products.update_one({"_id": stella["_id"]}, {"$set": {"stock": 2}})

        await carts.insert_one(
            {
                "_id": ObjectId(),
                "user_id": FAKE_USER_ID,
                "items": [{"product_id": str(stella["_id"]), "quantity": 5}],
            }
        )

        _mount_orders_and_app(test_app)
        for dep, override in auth_user_dep.items():
            test_app.dependency_overrides[dep] = override

        response = await test_client.post(
            "/",
            json=_build_order_payload(
                [{"product_id": str(stella["_id"]), "quantity": 5}]
            ),
        )

        # 409 with a detail that names the product and includes both numbers.
        assert response.status_code == 409, response.text
        body = response.json()
        assert "detail" in body
        detail = body["detail"]
        assert "Stella Artois 1L" in detail
        assert "2" in detail
        assert "5" in detail

        # Stock unchanged.
        after = await products.find_one({"_id": stella["_id"]})
        assert after["stock"] == 2
