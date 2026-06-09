"""Endpoint tests for inventory admin endpoints + orders HTTP surface.

These tests cover the PR #3 endpoint layer: they mount the inventory
and orders routers on the minimal test app (built by conftest) and
hit the HTTP routes via httpx.AsyncClient. The in-memory
mongomock-motor backend is the source of truth for products, alerts,
orders, and carts.

Tasks covered
-------------
T3.1  PUT /inventory/{id}/stock
T3.2  PUT /inventory/{id}/stock/add
T3.3  GET /inventory/alerts (sorted by timestamp desc)
T3.3  PUT /inventory/{id}/stock — non-admin 403
T3.4  POST /orders — full happy path with all stock helpers wired
T3.5  PUT /orders/admin/{id}/status — cancel + refund

T3.4 is marked @pytest.mark.xfail(strict=False, ...) because
create_order has a known race condition (separate non-atomic check
and decrement) tracked by the fix-stock-bugs change. T3.5 is marked
@pytest.mark.xfail(strict=False, ...) because update_order_status
has a known indentation bug (the for loop is outside the
"is cancel/refund" guard) tracked by the same change. T3.1, T3.2,
T3.3 are expected to pass against the current production code.

All tests are marked @pytest.mark.endpoint. Production code is
untouched. The minimal test app does NOT include MaintenanceModeMiddleware
and does NOT use the production lifespan, so no real MongoDB or
Redis connection is attempted.

Technical notes
---------------
* The orders router exposes its create endpoint at "/" (a bare
  prefix-less path), so the URL is "/". The order status admin
  endpoint is at "/admin/{order_id}/status".
* The inventory router exposes its PUT endpoints at "/{id}/stock"
  and "/{id}/stock/add", and the GET alerts endpoint at "/alerts".
* The router reads `new_stock` and `quantity_to_add` from a
  Body(..., embed=True) — the JSON must wrap the field name.
* The create_order flow reads from the user's cart in the
  `carts` collection (keyed by user_id), reads pricing from
  `pricing_settings`, sends a notification via `email_service`
  (autouse silenced), and writes the order to the `orders`
  collection.
* mongomock-motor 0.0.36 supports the same find/update API as
  motor for our purposes; the non-transactional code path in
  routers/orders.py is exercised here.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from bson import ObjectId
from fastapi import FastAPI

from routers import inventory as inventory_router
from routers import orders as orders_router
from routers import pricing_settings as pricing_settings_router
from security import (
    get_current_active_user_id,
    get_current_admin_user,
    get_current_user_token_data,
)
from tests.conftest import FAKE_USER_ID
from models import (
    Address,
    OrderStatus,
    PaymentMethod,
    TokenData,
    UserRole,
)


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


def _mount_inventory_and_app(test_app: FastAPI) -> None:
    """Mount the inventory router on the test app."""
    test_app.include_router(inventory_router.router)


def _mount_orders_and_app(test_app: FastAPI) -> None:
    """Mount the orders router (and pricing-settings as a sibling dep)."""
    test_app.include_router(orders_router.router)
    test_app.include_router(pricing_settings_router.router)


def _apply_admin_overrides(test_app: FastAPI, auth_admin_dep) -> None:
    """Apply the admin auth overrides (replaces the default user overrides)."""
    for dep, override in auth_admin_dep.items():
        test_app.dependency_overrides[dep] = override


def _apply_user_overrides(test_app: FastAPI, auth_user_dep) -> None:
    """Apply the regular user auth overrides."""
    for dep, override in auth_user_dep.items():
        test_app.dependency_overrides[dep] = override


def _build_order_payload(items: list[dict]) -> dict:
    """Build a JSON-serializable OrderCreate body for POST /orders/."""
    return {
        "items": items,
        "shipping_address": VALID_ADDRESS.model_dump(),
        "shipping_zone": "pickup",  # pickup is always free — no shipping math noise
    }


# ---------------------------------------------------------------------------
# T3.1 — PUT /inventory/{id}/stock (admin sets absolute stock)
# ---------------------------------------------------------------------------


class TestSetAbsoluteStock:
    @pytest.mark.endpoint
    async def test_admin_sets_stock_triggers_low_stock_alert(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """PUT /inventory/{id}/stock with new_stock=5 on a stock=20 product.

        Contract per the stock-control spec:
        - Product stock becomes 5.
        - A low-stock alert is created (stock <= threshold 10).

        The router uses Body(..., embed=True), so the JSON body must
        wrap the field name: `{"new_stock": 5}`.
        """
        products = test_db["products"]
        alerts = test_db["inventory_alerts"]

        # Pick Quilmes (seeded stock=20).
        quilmes = await products.find_one({"name": "Quilmes 1L"})
        assert quilmes["stock"] == 20
        product_id_str = str(quilmes["_id"])

        _mount_inventory_and_app(test_app)
        _apply_admin_overrides(test_app, auth_admin_dep)

        response = await test_client.put(
            f"/{product_id_str}/stock", json={"new_stock": 5}
        )

        # Spec: endpoint returns the updated Product model.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stock"] == 5
        assert body["name"] == "Quilmes 1L"

        # Spec: a low-stock alert must be created when stock <= threshold.
        after = await products.find_one({"_id": quilmes["_id"]})
        assert after["stock"] == 5

        alert = await alerts.find_one({"product_id": product_id_str})
        assert alert is not None, (
            "Spec violation: low-stock alert was not created after stock "
            "was set below threshold (10)."
        )
        assert alert["current_stock"] == 5
        assert alert["threshold"] == 10
        assert "Quilmes 1L" in alert["message"]


# ---------------------------------------------------------------------------
# T3.2 — PUT /inventory/{id}/stock/add (admin adds stock)
# ---------------------------------------------------------------------------


class TestAddToStock:
    @pytest.mark.endpoint
    async def test_admin_adds_stock_does_not_create_new_alert(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """PUT /inventory/{id}/stock/add with quantity_to_add=20 on stock=5.

        Contract per the stock-control spec:
        - Product stock becomes 25.
        - No new alert is created (stock is now well above threshold).

        The router uses Body(..., embed=True), so the JSON body must
        wrap the field name: `{"quantity_to_add": 20}`.
        """
        products = test_db["products"]
        alerts = test_db["inventory_alerts"]

        # Pick Stella (seeded stock=5) and pre-seed an existing alert
        # at the message that a stock=5 product would generate.
        stella = await products.find_one({"name": "Stella Artois 1L"})
        assert stella["stock"] == 5
        product_id_str = str(stella["_id"])

        existing_msg = f"El stock del producto '{stella['name']}' es bajo (5)."
        await alerts.insert_one(
            {
                "_id": ObjectId(),
                "product_id": product_id_str,
                "product_name": stella["name"],
                "current_stock": 5,
                "threshold": 10,
                "message": existing_msg,
                "timestamp": datetime.utcnow(),
            }
        )
        pre_count = await alerts.count_documents({"product_id": product_id_str})
        assert pre_count == 1

        _mount_inventory_and_app(test_app)
        _apply_admin_overrides(test_app, auth_admin_dep)

        response = await test_client.put(
            f"/{product_id_str}/stock/add", json={"quantity_to_add": 20}
        )

        # Spec: endpoint returns the updated Product.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stock"] == 25

        # Spec: no new alert created (stock now 25, above threshold 10).
        after = await products.find_one({"_id": stella["_id"]})
        assert after["stock"] == 25

        post_count = await alerts.count_documents({"product_id": product_id_str})
        assert post_count == 1, (
            "Spec violation: a new alert was created even though stock is "
            "now above threshold. Expected the existing alert to remain "
            "untouched (no duplicate)."
        )


# ---------------------------------------------------------------------------
# T3.3 — GET /inventory/alerts (sorted by timestamp desc)
# T3.3 — PUT /inventory/{id}/stock (non-admin returns 403)
# ---------------------------------------------------------------------------


class TestInventoryAlertsListing:
    @pytest.mark.endpoint
    async def test_list_alerts_sorted_by_timestamp_desc(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """Seed 3 alerts with different timestamps; admin call returns
        them with the most recent first.
        """
        alerts = test_db["inventory_alerts"]

        now = datetime.utcnow()
        seeded = [
            {
                "_id": ObjectId(),
                "product_id": str(ObjectId()),
                "product_name": "Alpha Beer",
                "current_stock": 3,
                "threshold": 10,
                "message": "oldest alert",
                "timestamp": now - timedelta(hours=2),
            },
            {
                "_id": ObjectId(),
                "product_id": str(ObjectId()),
                "product_name": "Beta Wine",
                "current_stock": 2,
                "threshold": 10,
                "message": "middle alert",
                "timestamp": now - timedelta(hours=1),
            },
            {
                "_id": ObjectId(),
                "product_id": str(ObjectId()),
                "product_name": "Gamma Spirit",
                "current_stock": 1,
                "threshold": 10,
                "message": "newest alert",
                "timestamp": now,
            },
        ]
        await alerts.insert_many(seeded)

        _mount_inventory_and_app(test_app)
        _apply_admin_overrides(test_app, auth_admin_dep)

        response = await test_client.get("/alerts")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body) == 3

        # The first element MUST be the most recent (newest alert).
        assert body[0]["message"] == "newest alert"
        assert body[0]["product_name"] == "Gamma Spirit"
        # And the order must be strictly descending.
        assert body[1]["message"] == "middle alert"
        assert body[2]["message"] == "oldest alert"


class TestNonAdminCannotModifyStock:
    @pytest.mark.endpoint
    async def test_non_admin_user_gets_403_on_set_stock(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """A non-admin (CUSTOMER role) calling PUT /inventory/{id}/stock
        must get HTTP 403 — the endpoint is admin-only.

        The conftest auth_user_dep fixture overrides get_current_admin_user
        to an admin token (so admin-only endpoints accept it for the
        positive tests). For THIS test we need a CUSTOMER-roles token
        that the get_current_admin_user dep will reject.
        """
        products = test_db["products"]
        quilmes = await products.find_one({"name": "Quilmes 1L"})
        product_id_str = str(quilmes["_id"])

        # Build a CUSTOMER token (NOT admin) for this test only.
        customer_token = TokenData(
            username="customer@example.com",
            user_id=FAKE_USER_ID,
            roles=[UserRole.CUSTOMER],
            age_verified=True,
        )
        _mount_inventory_and_app(test_app)
        test_app.dependency_overrides[get_current_user_token_data] = (
            lambda: customer_token
        )
        test_app.dependency_overrides[get_current_active_user_id] = (
            lambda: customer_token.user_id
        )
        # The conftest test_app fixture applies auth_user_dep which
        # ALSO overrides get_current_admin_user to an admin token.
        # We must REMOVE that override so the real dep runs and
        # rejects because the CUSTOMER token lacks the ADMIN role.
        test_app.dependency_overrides.pop(get_current_admin_user, None)

        response = await test_client.put(
            f"/{product_id_str}/stock", json={"new_stock": 5}
        )

        # Spec: HTTP 403 for non-admin on PUT /inventory/{id}/stock.
        assert response.status_code == 403, response.text

        # Stock must NOT have changed — the dep rejected before any write.
        after = await products.find_one({"_id": quilmes["_id"]})
        assert after["stock"] == 20  # original Quilmes stock


# ---------------------------------------------------------------------------
# T3.4 — POST /orders (full happy path with all stock helpers wired)
# ---------------------------------------------------------------------------


class TestFullOrderEndpoint:
    @pytest.mark.endpoint
    @pytest.mark.xfail(
        strict=False,
        reason=(
            "Race condition in create_order; the pre-check and the $inc "
            "decrement are not atomic. See fix-stock-bugs change."
        ),
    )
    async def test_full_order_end_to_end_decrements_stock(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """End-to-end: cart with one Stella (stock=5) → POST /orders
        → response includes the line → product stock=4.

        This is the endpoint-layer mirror of T2.1 (which is also xfail
        for the same race condition). Asserting the same contract at
        the HTTP tier catches regressions in the route + auth + cart
        read + order insert + stock decrement pipeline.
        """
        products = test_db["products"]
        carts = test_db["carts"]
        orders = test_db["orders"]

        stella = await products.find_one({"name": "Stella Artois 1L"})
        assert stella["stock"] == 5
        stella_id_str = str(stella["_id"])

        # Seed a cart for FAKE_USER_ID.
        await carts.insert_one(
            {
                "_id": ObjectId(),
                "user_id": FAKE_USER_ID,
                "items": [{"product_id": stella_id_str, "quantity": 1}],
            }
        )

        _mount_orders_and_app(test_app)
        _apply_user_overrides(test_app, auth_user_dep)

        response = await test_client.post(
            "/",
            json=_build_order_payload(
                [{"product_id": stella_id_str, "quantity": 1}]
            ),
        )

        # Spec: 201 Created, body has the order with one line item.
        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "Stella Artois 1L"
        assert body["items"][0]["quantity"] == 1

        # Spec: stock is now 4.
        after = await products.find_one({"_id": stella["_id"]})
        assert after["stock"] == 4

        # Spec: an order document was written.
        order_count = await orders.count_documents({"user_id": FAKE_USER_ID})
        assert order_count == 1


# ---------------------------------------------------------------------------
# T3.5 — PUT /orders/admin/{id}/status (cancel + refund)
# ---------------------------------------------------------------------------


def _seed_delivered_order(orders, products, user_id: str) -> tuple[str, list[ObjectId]]:
    """Seed an order with status=DELIVERED plus a parallel decrement
    on the product stocks (to simulate the state after a delivered
    order: stock has already been decremented at create time).

    Returns (order_id_str, list_of_product_oids).
    """
    quilmes = products.find_one({"_id": ObjectId("507f1f77bcf86cd799439011")})
    stella = products.find_one({"_id": ObjectId("507f1f77bcf86cd799439012")})
    product_oids = [quilmes["_id"], stella["_id"]]

    order_id = ObjectId()
    orders.insert_one(
        {
            "_id": order_id,
            "user_id": user_id,
            "items": [
                {
                    "product_id": str(quilmes["_id"]),
                    "name": "Quilmes 1L",
                    "quantity": 2,
                    "price_at_purchase": 1500.0,
                },
                {
                    "product_id": str(stella["_id"]),
                    "name": "Stella Artois 1L",
                    "quantity": 1,
                    "price_at_purchase": 2200.0,
                },
            ],
            "total_amount": 5200.0,
            "status": OrderStatus.DELIVERED.value,
            "shipping_address": VALID_ADDRESS.model_dump(),
            "shipping_zone": "pickup",
            "shipping_cost": 0.0,
            "payment_method": PaymentMethod.MERCADO_PAGO.value,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
    )

    # Simulate the stock that was already decremented at order creation:
    # Quilmes (stock=20) - 2 = 18; Stella (stock=5) - 1 = 4.
    products.update_one({"_id": quilmes["_id"]}, {"$set": {"stock": 18}})
    products.update_one({"_id": stella["_id"]}, {"$set": {"stock": 4}})

    return str(order_id), product_oids


class TestCancelAndRefundRestoreStock:
    @pytest.mark.endpoint
    @pytest.mark.xfail(
        strict=False,
        reason=(
            "Indentation bug in update_order_status: the for loop that "
            "restores stock is at the wrong indentation level and runs "
            "for every status change, not just CANCELLED/REFUNDED. "
            "See fix-stock-bugs change."
        ),
    )
    async def test_cancel_status_restores_stock(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """An admin PUTs the order status to CANCELLED on a DELIVERED
        order. Each product's stock must be incremented back by the
        original ordered quantity.

        Quilmes: 18 → 18 + 2 = 20
        Stella:  4  → 4  + 1 = 5

        Note: the router signature is
            new_status: OrderStatus
        (no Body() wrapper). FastAPI 0.116.1 treats an Enum without
        Body() as a QUERY parameter, not a body parameter. We send
        the status via ?new_status=Cancelado, matching the production
        contract. The OpenAPI spec confirms this: query params for
        update_order_status.
        """
        products = test_db["products"]
        orders = test_db["orders"]

        order_id_str, product_oids = _seed_delivered_order(
            orders, products, FAKE_USER_ID
        )

        _mount_orders_and_app(test_app)
        _apply_admin_overrides(test_app, auth_admin_dep)

        response = await test_client.put(
            f"/admin/{order_id_str}/status",
            params={"new_status": OrderStatus.CANCELLED.value},
        )

        # Spec: 200 with the updated order.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == OrderStatus.CANCELLED.value

        # Spec: stock restored for every line item.
        quilmes = await products.find_one(
            {"_id": ObjectId("507f1f77bcf86cd799439011")}
        )
        stella = await products.find_one(
            {"_id": ObjectId("507f1f77bcf86cd799439012")}
        )
        assert quilmes["stock"] == 20
        assert stella["stock"] == 5

    @pytest.mark.endpoint
    @pytest.mark.xfail(
        strict=False,
        reason=(
            "Indentation bug in update_order_status; see fix-stock-bugs."
        ),
    )
    async def test_refund_status_restores_stock(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """Same as the cancel case but with status=REFUNDED.

        The spec says both CANCELLED and REFUNDED must restore stock.
        Sends new_status as a query param (see the cancel test for the
        rationale on FastAPI's Enum-as-query behavior).
        """
        products = test_db["products"]
        orders = test_db["orders"]

        order_id_str, _ = _seed_delivered_order(
            orders, products, FAKE_USER_ID
        )

        _mount_orders_and_app(test_app)
        _apply_admin_overrides(test_app, auth_admin_dep)

        response = await test_client.put(
            f"/admin/{order_id_str}/status",
            params={"new_status": OrderStatus.REFUNDED.value},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == OrderStatus.REFUNDED.value

        quilmes = await products.find_one(
            {"_id": ObjectId("507f1f77bcf86cd799439011")}
        )
        stella = await products.find_one(
            {"_id": ObjectId("507f1f77bcf86cd799439012")}
        )
        assert quilmes["stock"] == 20
        assert stella["stock"] == 5
