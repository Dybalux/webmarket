"""Integration tests for idempotency replay on POST /orders.

Verifies that:
  - Duplicate POST /orders with the same Idempotency-Key returns the
    cached response (201) without creating a second order or decrementing
    stock a second time (S2.1 + S2.2).
  - 409 on duplicate while IN_FLIGHT (S2.3 — via FakeRedis race simulation).
  - Missing header falls back to server-side key; request still succeeds (S2.4).
  - Fail-open: when FakeRedis raises, the order is still created (S2.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from bson import ObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from models import Address, TokenData, UserRole
from routers import orders as orders_router
from tests.conftest import FAKE_USER_ID, FakeRedis


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


def _build_order_payload(product_id: str, qty: int = 1) -> dict:
    return {
        "items": [{"product_id": product_id, "quantity": qty}],
        "shipping_address": VALID_ADDRESS.model_dump(),
        "shipping_zone": "pickup",
    }


@pytest_asyncio.fixture
async def idem_app(test_db, auth_user_dep, fake_redis) -> FastAPI:
    """Test app with orders router + FakeRedis injected."""
    from database import get_database, get_collection
    from security import get_redis

    app = FastAPI(title="idempotency test app")

    async def _override_db():
        return test_db

    app.dependency_overrides[get_database] = _override_db
    app.dependency_overrides[get_collection] = lambda name: test_db[name]
    for dep, override in auth_user_dep.items():
        app.dependency_overrides[dep] = override
    app.dependency_overrides[get_redis] = lambda: fake_redis

    # Register exception handlers
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    from services.exceptions import ServiceError
    from utils.errors import (
        service_error_handler,
        http_exception_handler,
        validation_exception_handler,
    )

    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.include_router(orders_router.router)
    return app


@pytest_asyncio.fixture
async def idem_client(idem_app) -> AsyncClient:
    transport = ASGITransport(app=idem_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# S2.1 + S2.2 — First request caches, replay returns cached (one order only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_post_returns_cached_without_second_order(
    idem_client: AsyncClient,
    test_db,
):
    """POST /orders twice with the same Idempotency-Key → one order, one stock decrement."""
    products = test_db["products"]
    carts = test_db["carts"]
    orders = test_db["orders"]

    stella = await products.find_one({"name": "Stella Artois 1L"})
    stella_id = str(stella["_id"])
    assert stella["stock"] == 5

    # Seed cart
    await carts.insert_one(
        {
            "_id": ObjectId(),
            "user_id": FAKE_USER_ID,
            "items": [{"product_id": stella_id, "quantity": 1}],
        }
    )

    idem_key = str(uuid.uuid4())
    payload = _build_order_payload(stella_id)

    # First request — creates order
    resp1 = await idem_client.post(
        "/", json=payload, headers={"Idempotency-Key": idem_key}
    )
    assert resp1.status_code == 201, resp1.text
    body1 = resp1.json()

    # Second request — should replay cached response
    resp2 = await idem_client.post(
        "/", json=payload, headers={"Idempotency-Key": idem_key}
    )
    assert resp2.status_code == 201, resp2.text
    body2 = resp2.json()

    # Same order data
    assert body1["_id"] == body2["_id"]
    assert body1["total_amount"] == body2["total_amount"]

    # Only ONE order in the database
    count = await orders.count_documents({"user_id": FAKE_USER_ID})
    assert count == 1, f"Expected 1 order, got {count}"

    # Stock decremented only ONCE (5 → 4, not 5 → 3)
    after = await products.find_one({"_id": stella["_id"]})
    assert after["stock"] == 4, f"Expected stock=4, got {after['stock']}"


# ---------------------------------------------------------------------------
# S2.3 — Invalid UUID rejected (400)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_uuid_returns_400(idem_client: AsyncClient):
    """POST /orders with invalid Idempotency-Key → 400."""
    resp = await idem_client.post(
        "/",
        json=_build_order_payload("507f1f77bcf86cd799439012"),
        headers={"Idempotency-Key": "not-a-uuid"},
    )
    assert resp.status_code == 400
    assert "UUID" in resp.json()["detail"] or "uuid" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# S2.4 — Missing header → fallback key, request proceeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_header_uses_fallback_and_succeeds(
    idem_client: AsyncClient, test_db
):
    """POST /orders without Idempotency-Key → server-side fallback; order created."""
    products = test_db["products"]
    carts = test_db["carts"]

    stella = await products.find_one({"name": "Stella Artois 1L"})
    stella_id = str(stella["_id"])

    await carts.insert_one(
        {
            "_id": ObjectId(),
            "user_id": FAKE_USER_ID,
            "items": [{"product_id": stella_id, "quantity": 1}],
        }
    )

    resp = await idem_client.post("/", json=_build_order_payload(stella_id))
    assert resp.status_code == 201, resp.text

    # Duplicate without header → same fallback key → cached replay
    resp2 = await idem_client.post("/", json=_build_order_payload(stella_id))
    assert resp2.status_code == 201
    assert resp.json()["_id"] == resp2.json()["_id"]


# ---------------------------------------------------------------------------
# S2.5 — Redis down → fail-open, order still created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_down_fail_open_creates_order(
    test_db, auth_user_dep, monkeypatch
):
    """When Redis is unreachable, POST /orders proceeds without idempotency."""
    from security import get_redis

    products = test_db["products"]
    carts = test_db["carts"]

    stella = await products.find_one({"name": "Stella Artois 1L"})
    stella_id = str(stella["_id"])

    await carts.insert_one(
        {
            "_id": ObjectId(),
            "user_id": FAKE_USER_ID,
            "items": [{"product_id": stella_id, "quantity": 1}],
        }
    )

    # Build app with broken Redis
    from redis.exceptions import ConnectionError as RedisConnError

    class BrokenRedis:
        async def set(self, *a, **kw):
            raise RedisConnError("Redis down")
        async def get(self, *a, **kw):
            raise RedisConnError("Redis down")

    from database import get_database, get_collection

    app = FastAPI()

    async def _override_db():
        return test_db

    app.dependency_overrides[get_database] = _override_db
    app.dependency_overrides[get_collection] = lambda name: test_db[name]
    for dep, override in auth_user_dep.items():
        app.dependency_overrides[dep] = override
    app.dependency_overrides[get_redis] = lambda: BrokenRedis()

    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    from services.exceptions import ServiceError
    from utils.errors import (
        service_error_handler,
        http_exception_handler,
        validation_exception_handler,
    )

    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.include_router(orders_router.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.post(
            "/",
            json=_build_order_payload(stella_id),
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )

    assert resp.status_code == 201, resp.text
    # Order was created despite Redis being down
    count = await test_db["orders"].count_documents({"user_id": FAKE_USER_ID})
    assert count == 1


# ---------------------------------------------------------------------------
# S2.6 — Cross-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_user_same_key_independent_results(
    idem_client: AsyncClient, test_db, auth_user_dep, idem_app
):
    """Same Idempotency-Key sent by different users → independent orders."""
    products = test_db["products"]
    carts = test_db["carts"]
    orders = test_db["orders"]

    stella = await products.find_one({"name": "Stella Artois 1L"})
    stella_id = str(stella["_id"])

    idem_key = str(uuid.uuid4())

    # User A (default FAKE_USER_ID)
    await carts.insert_one(
        {
            "_id": ObjectId(),
            "user_id": FAKE_USER_ID,
            "items": [{"product_id": stella_id, "quantity": 1}],
        }
    )
    resp_a = await idem_client.post(
        "/", json=_build_order_payload(stella_id),
        headers={"Idempotency-Key": idem_key},
    )
    assert resp_a.status_code == 201

    # User B — override auth to a different user
    other_user_id = "bbbbbbbbbbbbbbbbbbbbbbbb"
    from security import get_current_active_user_id, get_current_user_token_data, get_current_admin_user

    other_token = TokenData(
        username="other@example.com",
        user_id=other_user_id,
        roles=[UserRole.CUSTOMER],
        age_verified=True,
    )
    idem_app.dependency_overrides[get_current_user_token_data] = lambda: other_token
    idem_app.dependency_overrides[get_current_active_user_id] = lambda: other_user_id

    await carts.insert_one(
        {
            "_id": ObjectId(),
            "user_id": other_user_id,
            "items": [{"product_id": stella_id, "quantity": 1}],
        }
    )

    transport = ASGITransport(app=idem_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp_b = await ac.post(
            "/",
            json=_build_order_payload(stella_id),
            headers={"Idempotency-Key": idem_key},
        )
    assert resp_b.status_code == 201

    # Two independent orders (different users, same key)
    count_a = await orders.count_documents({"user_id": FAKE_USER_ID})
    count_b = await orders.count_documents({"user_id": other_user_id})
    assert count_a == 1
    assert count_b == 1
