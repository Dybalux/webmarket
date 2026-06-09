"""Integration tests for low-stock alert deduplication via POST /orders.

These tests verify the alert side-effect of the order flow at the
integration tier. They mount the orders router for the alert-on-order
scenario and use the inventory helper directly for the dedup scenario
(because that helper is the only public surface that performs dedup).

  T2.5 — order that drops stock below the threshold must create an
         InventoryAlert with current_stock and threshold recorded
  T2.6 — a pre-existing alert with the matching message must block a
         second insert (dedup)

T2.5 is marked @pytest.mark.xfail because the current `create_order`
implementation does not call `check_and_create_alert` — only
inventory router endpoints do. The follow-up fix-stock-bugs change
will make this pass.

T2.6 is not xfail: the dedup logic itself works (verified by the
unit test test_inventory_alerts.py::TestAlertDeduplication). This
test asserts the same contract at the integration tier.

All tests marked @pytest.mark.integration.
"""

from __future__ import annotations

from datetime import datetime

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
    test_app.include_router(orders_router.router)
    test_app.include_router(pricing_settings_router.router)


def _build_order_payload(items: list[dict]) -> dict:
    return {
        "items": items,
        "shipping_address": VALID_ADDRESS.model_dump(),
        "shipping_zone": "pickup",
    }


# ---------------------------------------------------------------------------
# T2.5 — Low-stock alert on order
# ---------------------------------------------------------------------------


class TestLowStockAlertOnOrder:
    @pytest.mark.integration
    @pytest.mark.xfail(
        strict=False,
        reason=(
            "create_order does not call check_and_create_alert. "
            "Spec says it should; current code only decrements stock. "
            "See fix-stock-bugs change."
        ),
    )
    async def test_order_below_threshold_creates_alert(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """stock=12 → order of 4 → stock=8 (below threshold 10) → InventoryAlert must exist.

        Per the stock-control spec: when an order causes a product's
        stock to cross below `LOW_STOCK_THRESHOLD` (10), an
        `InventoryAlert` document MUST be created. The current
        implementation of `create_order` only decrements stock and
        never calls `check_and_create_alert`, so this contract is not
        honored. Marked xfail — see fix-stock-bugs.
        """
        products = test_db["products"]
        carts = test_db["carts"]
        alerts = test_db["inventory_alerts"]

        # Use Malbec (seeded at 12) and order 4 → 8.
        malbec = await products.find_one({"name": "Vino Malbec 750ml"})
        assert malbec["stock"] == 12
        await carts.insert_one(
            {
                "_id": ObjectId(),
                "user_id": FAKE_USER_ID,
                "items": [{"product_id": str(malbec["_id"]), "quantity": 4}],
            }
        )

        _mount_orders_and_app(test_app)
        for dep, override in auth_user_dep.items():
            test_app.dependency_overrides[dep] = override

        response = await test_client.post(
            "/",
            json=_build_order_payload(
                [{"product_id": str(malbec["_id"]), "quantity": 4}]
            ),
        )

        # The order itself should still succeed (stock decrement works).
        assert response.status_code == 201, response.text
        after = await products.find_one({"_id": malbec["_id"]})
        assert after["stock"] == 8

        # Contract per spec: an InventoryAlert for this product must
        # exist with current_stock=8 and threshold=10.
        alert = await alerts.find_one({"product_id": str(malbec["_id"])})
        assert alert is not None, (
            "Spec violation: create_order did not create an alert "
            "when stock crossed below threshold."
        )
        assert alert["current_stock"] == 8
        assert alert["threshold"] == 10


# ---------------------------------------------------------------------------
# T2.6 — Alert deduplication
# ---------------------------------------------------------------------------


class TestAlertDedup:
    @pytest.mark.integration
    async def test_no_new_alert_on_second_stock_drop_with_matching_message(
        self, test_app, test_db
    ):
        """Pre-existing alert at the same message blocks the second insert.

        This is the integration-level mirror of the unit test in
        test_inventory_alerts.py — we call the inventory helper
        directly (the only public surface that does dedup) and assert
        the count stays at 1.
        """
        from routers.inventory import check_and_create_alert

        products = test_db["products"]
        alerts = test_db["inventory_alerts"]

        malbec = await products.find_one({"name": "Vino Malbec 750ml"})
        product_id_str = str(malbec["_id"])

        # Seed an alert at the same message the helper would generate.
        msg = f"El stock del producto '{malbec['name']}' es bajo (8)."
        await alerts.insert_one(
            {
                "_id": ObjectId(),
                "product_id": product_id_str,
                "product_name": malbec["name"],
                "current_stock": 8,
                "threshold": 10,
                "message": msg,
                "timestamp": datetime.utcnow(),
            }
        )

        # Drop stock to 8 to match the alert message.
        await products.update_one({"_id": malbec["_id"]}, {"$set": {"stock": 8}})

        # First call would normally insert, but the matching message blocks it.
        await check_and_create_alert(products, alerts, product_id_str)

        # Still exactly one alert — no duplicate.
        count = await alerts.count_documents({"product_id": product_id_str})
        assert count == 1
