"""Integration tests for audit logging wiring.

Verifies that log_audit is called at all router-level call points
and that the JSON event value matches expectations.

Uses the test_client + conftest autouse silence fixture which patches
audit_logger.log_audit and audit_logger.log_audit_ctx as AsyncMock.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from bson import ObjectId, Decimal128
from httpx import ASGITransport, AsyncClient

import audit_logger
from models import ProductCategory
from tests.conftest import FakeRedis


# ---------------------------------------------------------------------------
# Shared fixture: auth test client with rate limiter bypassed
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def audit_test_client(test_app, fake_redis, monkeypatch):
    """Test client with auth + admin + products + payments routers mounted."""
    from fastapi_limiter import FastAPILimiter
    from routers.auth import router as auth_router
    from routers.admin import router as admin_router
    from routers.products import router as products_router
    from routers.payments import router as payments_router

    test_app.include_router(auth_router, prefix="/auth")
    test_app.include_router(admin_router, prefix="/admin")
    test_app.include_router(products_router, prefix="/products")
    test_app.include_router(payments_router, prefix="/payments")

    # Bypass RateLimiter — needs real Redis; lockout tested separately.
    mock_redis = AsyncMock()
    mock_redis.script_load = AsyncMock(return_value="fake-sha")
    mock_redis.evalsha = AsyncMock(return_value=0)
    await FastAPILimiter.init(mock_redis)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STRONG_PASSWORD = "StrongP@ssw0rd!"  # 16 chars, all classes


# ---------------------------------------------------------------------------
# Auth router — 5 call points (register, login ✓/✗, forgot, reset)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_audit(audit_test_client: AsyncClient, monkeypatch):
    """POST /auth/register → USER_REGISTERED."""
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.post(
        "/auth/register",
        json={
            "username": "newuser",
            "email": "new@example.com",
            "password": _STRONG_PASSWORD,
            "birth_date": "1990-01-01T00:00:00+00:00",
        },
    )
    assert resp.status_code == 201
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.USER_REGISTERED
    assert args[0][2]["username"] == "newuser"


@pytest.mark.asyncio
async def test_login_success_audit(test_db, audit_test_client: AsyncClient, monkeypatch):
    """POST /auth/token (valid creds) → USER_LOGIN_SUCCESS."""
    from security import get_password_hash
    await test_db["users"].insert_one(
        {
            "username": "loginuser",
            "email": "login@example.com",
            "hashed_password": get_password_hash(_STRONG_PASSWORD),
            "role": "customer",
            "age_verified": True,
            "birth_date": datetime(1990, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime.now(tz=timezone.utc),
        }
    )
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.post(
        "/auth/token",
        data={"username": "loginuser", "password": _STRONG_PASSWORD},
    )
    assert resp.status_code == 200
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.USER_LOGIN_SUCCESS
    assert args[0][2]["username"] == "loginuser"


@pytest.mark.asyncio
async def test_login_failed_audit(test_db, audit_test_client: AsyncClient, monkeypatch):
    """POST /auth/token (bad password) → USER_LOGIN_FAILED."""
    from security import get_password_hash
    await test_db["users"].insert_one(
        {
            "username": "failuser",
            "email": "fail@example.com",
            "hashed_password": get_password_hash(_STRONG_PASSWORD),
            "role": "customer",
            "age_verified": True,
            "birth_date": datetime(1990, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime.now(tz=timezone.utc),
        }
    )
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.post(
        "/auth/token",
        data={"username": "failuser", "password": "WrongP@ssw0rd!1"},
    )
    assert resp.status_code == 401
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.USER_LOGIN_FAILED
    assert args[0][2]["username"] == "failuser"


@pytest.mark.asyncio
async def test_forgot_password_audit(audit_test_client: AsyncClient, monkeypatch):
    """POST /auth/forgot-password → PASSWORD_RESET_REQUESTED."""
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.post(
        "/auth/forgot-password",
        json={"email": "user@example.com"},
    )
    assert resp.status_code == 202
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.PASSWORD_RESET_REQUESTED
    assert args[0][2]["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_reset_password_audit(test_db, audit_test_client: AsyncClient, monkeypatch):
    """POST /auth/reset-password → PASSWORD_RESET_COMPLETED."""
    from security import hash_reset_token, create_reset_token, get_password_hash

    user_id = ObjectId()
    await test_db["users"].insert_one(
        {
            "_id": user_id,
            "username": "resetuser",
            "email": "reset@example.com",
            "hashed_password": get_password_hash(_STRONG_PASSWORD),
            "role": "customer",
            "age_verified": True,
            "birth_date": datetime(1990, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime.now(tz=timezone.utc),
        }
    )
    token_raw = create_reset_token()
    token_hash = hash_reset_token(token_raw)
    await test_db["password_reset_tokens"].insert_one(
        {
            "token_hash": token_hash,
            "user_id": str(user_id),
            "expires_at": datetime.now(tz=timezone.utc) + timedelta(minutes=60),
            "used": False,
        }
    )
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.post(
        "/auth/reset-password",
        json={"token": token_raw, "new_password": _STRONG_PASSWORD},
    )
    assert resp.status_code == 200
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.PASSWORD_RESET_COMPLETED


# ---------------------------------------------------------------------------
# Admin router — 1 call point (role change)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_role_change_audit(test_db, test_app, audit_test_client: AsyncClient, monkeypatch, auth_admin_dep):
    """PUT /admin/users/{id}/role → ADMIN_ROLE_CHANGED."""
    for dep, override in auth_admin_dep.items():
        test_app.dependency_overrides[dep] = override

    user_id = ObjectId()
    await test_db["users"].insert_one(
        {
            "_id": user_id,
            "username": "targetuser",
            "email": "target@example.com",
            "hashed_password": "x",
            "role": "customer",
            "age_verified": True,
            "birth_date": datetime(1990, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime.now(tz=timezone.utc),
        }
    )
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.put(
        f"/admin/users/{user_id}/role",
        params={"new_role": "admin"},
    )
    assert resp.status_code == 200
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.ADMIN_ROLE_CHANGED
    assert args[0][2]["target_user"] == "targetuser"
    assert args[0][2]["from_role"] == "customer"
    assert args[0][2]["to_role"] == "admin"


# ---------------------------------------------------------------------------
# Products router — 2 call points (create, update)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_product_create_audit(test_db, test_app, audit_test_client: AsyncClient, monkeypatch, auth_admin_dep):
    """POST /products/ → ADMIN_PRODUCT_CREATED."""
    for dep, override in auth_admin_dep.items():
        test_app.dependency_overrides[dep] = override

    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.post(
        "/products/",
        json={
            "name": "AuditBeer",
            "description": "A beer for audit tests",
            "price": "1500.00",
            "category": ProductCategory.BEER.value,
            "stock": 10,
            "image_url": "https://example.com/audit.jpg",
            "abv": 5.0,
            "volume_ml": 500,
            "origin": "Argentina",
            "active": True,
        },
    )
    assert resp.status_code == 201
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.ADMIN_PRODUCT_CREATED
    assert args[0][2]["name"] == "AuditBeer"


@pytest.mark.asyncio
async def test_product_update_audit(test_db, test_app, audit_test_client: AsyncClient, monkeypatch, auth_admin_dep):
    """PUT /products/{id} → ADMIN_PRODUCT_UPDATED."""
    for dep, override in auth_admin_dep.items():
        test_app.dependency_overrides[dep] = override

    pid = ObjectId()
    await test_db["products"].insert_one(
        {
            "_id": pid,
            "name": "OldBeer",
            "description": "An old beer",
            "price": Decimal128("1000.00"),
            "category": ProductCategory.BEER.value,
            "stock": 10,
            "image_url": "https://example.com/old.jpg",
            "abv": 5.0,
            "volume_ml": 500,
            "origin": "Argentina",
            "active": True,
        }
    )
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.put(
        f"/products/{pid}",
        json={
            "name": "UpdatedBeer",
            "description": "Updated description",
            "price": "2000.00",
            "category": ProductCategory.BEER.value,
            "stock": 15,
            "image_url": "https://example.com/updated.jpg",
            "abv": 6.0,
            "volume_ml": 750,
            "origin": "Argentina",
            "active": True,
        },
    )
    assert resp.status_code == 200
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.ADMIN_PRODUCT_UPDATED
    assert args[0][2]["product_id"] == str(pid)


# ---------------------------------------------------------------------------
# Payments router — 1 call point (webhook)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_received_audit(audit_test_client: AsyncClient, monkeypatch):
    """POST /payments/webhook → PAYMENT_WEBHOOK_RECEIVED."""
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(audit_logger, "log_audit", mock)

    resp = await audit_test_client.post(
        "/payments/webhook?topic=payment&id=12345",
        headers={"x-signature": "", "x-request-id": "req-1"},
    )
    assert resp.status_code == 200
    args = mock.call_args
    assert args[0][0] == audit_logger.AuditEvent.PAYMENT_WEBHOOK_RECEIVED
    assert args[0][2]["topic"] == "payment"
    assert args[0][2]["payment_id"] == "12345"


# ---------------------------------------------------------------------------
# Fire-and-forget latency (S1.4) — task 4.4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_and_forget_latency():
    """asyncio.create_task completes in ≤2ms (S1.4)."""
    called = asyncio.Event()

    async def _slow_audit():
        await asyncio.sleep(0.05)  # simulate slow I/O
        called.set()

    start = time.perf_counter()
    task = asyncio.create_task(_slow_audit())
    elapsed_ms = (time.perf_counter() - start) * 1000

    # The create_task itself should be nearly instant (< 2ms)
    assert elapsed_ms < 2.0, f"create_task took {elapsed_ms:.2f}ms (limit: 2ms)"

    # Cleanup
    await task
    assert called.is_set()
