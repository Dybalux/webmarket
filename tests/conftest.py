"""
Shared pytest fixtures for the webmarket test suite.

This conftest provides:

  Database fixtures
  -----------------
  - mock_db: a fresh in-memory mongomock-motor client per test (function scope)
  - reset_db_singleton: repoints database.db to the mock client for the test
  - mock_products_collection / mock_alerts_collection / mock_orders_collection:
    pre-seeded collections with the fixtures used by the stock-control tests

  Auth dependency overrides
  -------------------------
  - auth_user_dep / auth_admin_dep: drop-in overrides for the three auth deps
    from security.py (get_current_user_token_data, get_current_admin_user,
    get_current_active_user_id). Tests opt in by listing the fixture name.

  Test app + client
  -----------------
  - test_app: a minimal FastAPI() instance that:
      * does NOT import main.py (so lifespan / middleware chain is bypassed)
      * does NOT include MaintenanceModeMiddleware
      * has its dependency_overrides wired so get_database / get_collection
        return the mock collections for this test
  - test_client: an httpx.AsyncClient bound to test_app via ASGITransport.
    Use this for any router-level or HTTP-level test.

  Side-effect silencers
  ---------------------
  - monkeypatched audit logger and email service so tests never hit the
    filesystem, Resend, or the network for real.

  IMPORTANT
  ---------
  mongomock-motor does NOT support MongoDB transactions. stock_helpers tests
  that need the transactional code path (validate_and_reserve_stock +
  update_stock_atomic + rollback_stock) must inject AsyncMock sessions and
  assert behavior, not true atomicity.
"""

from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from bson import ObjectId, Decimal128
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

import database
from models import (
    ProductCategory,
    TokenData,
    UserRole,
)
from security import (
    get_current_active_user_id,
    get_current_admin_user,
    get_current_user_token_data,
    get_redis,
)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

# In-memory mongomock does not need a URI, but tests sometimes want a string
# to pass to dependency overrides or to assert "we never touched the real DB".
TEST_DB_URI = "mongodb://mongomock-motor/in-memory"
TEST_DB_NAME = "webmarket_test"


@pytest.fixture
def test_db_uri() -> str:
    """Return the in-memory mongomock URI.

    Provided for tests that want to assert they never touch the real DB. Most
    tests should use `test_db` / `mock_db` directly instead of building a URI.
    """
    return TEST_DB_URI


@pytest.fixture
def mock_db() -> AsyncMongoMockClient:
    """Fresh in-memory mongomock client per test.

    Use this when you need a client but want a clean state every test.
    """
    return AsyncMongoMockClient()


@pytest_asyncio.fixture
async def reset_db_singleton(mock_db: AsyncMongoMockClient, monkeypatch):
    """Repoint `database.db` to the in-memory mock for the duration of the test.

    Restores the original singleton afterwards. Yields the in-memory database
    so tests can access collections directly:

        async def test_x(reset_db_singleton):
            db = reset_db_singleton
            await db["products"].insert_one({...})
    """
    in_memory_db = mock_db[TEST_DB_NAME]
    monkeypatch.setattr(database.db, "client", mock_db, raising=False)
    monkeypatch.setattr(database.db, "db", in_memory_db, raising=False)
    yield in_memory_db
    # monkeypatch restores the original attributes (or deletes them if they
    # were not set originally, since we passed raising=False above).


# ---------------------------------------------------------------------------
# Seeded test data
# ---------------------------------------------------------------------------

SAMPLE_PRODUCTS: list[dict] = [
    {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "name": "Quilmes 1L",
        "description": "Cerveza Quilmes 1 litro",
        "price": Decimal128("1500.00"),
        "category": ProductCategory.BEER.value,
        "stock": 20,
        "image_url": "https://example.com/quilmes.jpg",
        "abv": 4.9,
        "volume_ml": 1000,
        "origin": "Argentina",
        "active": True,
    },
    {
        "_id": ObjectId("507f1f77bcf86cd799439012"),
        "name": "Stella Artois 1L",
        "description": "Cerveza Stella Artois 1L",
        "price": Decimal128("2200.00"),
        "category": ProductCategory.BEER.value,
        "stock": 5,
        "image_url": "https://example.com/stella.jpg",
        "abv": 5.0,
        "volume_ml": 1000,
        "origin": "Belgium",
        "active": True,
    },
    {
        "_id": ObjectId("507f1f77bcf86cd799439013"),
        "name": "Fernet Branca 750ml",
        "description": "Fernet Branca 750ml",
        "price": Decimal128("8500.00"),
        "category": ProductCategory.SPIRITS_FERNET.value,
        "stock": 0,  # out of stock — used by filter tests
        "image_url": "https://example.com/fernet.jpg",
        "abv": 40.0,
        "volume_ml": 750,
        "origin": "Italy",
        "active": True,
    },
    {
        "_id": ObjectId("507f1f77bcf86cd799439014"),
        "name": "Vino Malbec 750ml",
        "description": "Vino tinto Malbec",
        "price": Decimal128("4200.00"),
        "category": ProductCategory.WINE_RED.value,
        "stock": 12,
        "image_url": "https://example.com/malbec.jpg",
        "abv": 13.5,
        "volume_ml": 750,
        "origin": "Mendoza",
        "active": True,
    },
]


@pytest_asyncio.fixture
async def test_db(reset_db_singleton) -> AsyncIOMotorDatabase:
    """In-memory database with the products collection pre-seeded.

    Use this when the test needs the products fixture ready to go:

        async def test_x(test_db):
            products = test_db["products"]
            docs = await products.find({}).to_list(None)
            assert len(docs) == 4
    """
    db = reset_db_singleton
    products = db["products"]
    await products.insert_many([dict(doc) for doc in SAMPLE_PRODUCTS])
    return db


@pytest_asyncio.fixture
async def mock_products_collection(test_db) -> AsyncIOMotorCollection:
    return test_db["products"]


@pytest_asyncio.fixture
async def mock_alerts_collection(test_db) -> AsyncIOMotorCollection:
    return test_db["inventory_alerts"]


@pytest_asyncio.fixture
async def mock_orders_collection(test_db) -> AsyncIOMotorCollection:
    return test_db["orders"]


# ---------------------------------------------------------------------------
# Auth dependency overrides
# ---------------------------------------------------------------------------

# Default fake identities used by auth_user_dep / auth_admin_dep
FAKE_USER_ID = "65f0a1b2c3d4e5f6a7b8c9d0"
FAKE_ADMIN_ID = "65f0a1b2c3d4e5f6a7b8c9d1"


def _make_user_token_data(role: UserRole) -> TokenData:
    user_id = FAKE_ADMIN_ID if role == UserRole.ADMIN else FAKE_USER_ID
    return TokenData(
        username=f"{role.value}@example.com",
        user_id=user_id,
        roles=[role],
        age_verified=True,
    )


@pytest.fixture
def auth_user_dep(monkeypatch):
    """Override all three auth dependencies with a normal CUSTOMER token."""
    token = _make_user_token_data(UserRole.CUSTOMER)
    # Tests apply these with `app.dependency_overrides[...] = ...` or by
    # pulling the values off the fixture and registering them on test_app.
    return {
        get_current_user_token_data: lambda: token,
        get_current_active_user_id: lambda: token.user_id,
        get_current_admin_user: lambda: _make_user_token_data(UserRole.ADMIN),
    }


@pytest.fixture
def auth_admin_dep(monkeypatch):
    """Override all three auth dependencies with an ADMIN token."""
    token = _make_user_token_data(UserRole.ADMIN)
    return {
        get_current_user_token_data: lambda: token,
        get_current_active_user_id: lambda: token.user_id,
        get_current_admin_user: lambda: token,
    }


# ---------------------------------------------------------------------------
# Fake Redis for lockout tests (F-017)
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal async in-memory Redis substitute for lockout helpers.

    Implements only the methods used by security.py lockout helpers:
    get, setex, incr, delete, ttl, expire.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, float] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value
        self._ttls[key] = ttl

    async def expire(self, key: str, ttl: int) -> None:
        if key in self._store:
            self._ttls[key] = ttl

    async def incr(self, key: str) -> int:
        val = int(self._store.get(key, 0)) + 1
        self._store[key] = str(val)
        return val

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)
            self._ttls.pop(k, None)

    async def ttl(self, key: str) -> int:
        if key not in self._store:
            return -2
        return int(self._ttls.get(key, 0))


@pytest.fixture
def fake_redis() -> FakeRedis:
    """Fresh FakeRedis instance per test."""
    return FakeRedis()


# ---------------------------------------------------------------------------
# Side-effect silencers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def silence_side_effects(monkeypatch):
    """Prevent tests from sending real emails or writing real audit logs.

    Autouse so it applies to every test in the suite; the cost is one mock
    call per fixture load, which is negligible.
    """
    # Patch the symbols routers actually call: audit_logger.log_audit and
    # email_service.send_new_order_notification. Both are async in this project.
    import audit_logger
    import email_service

    monkeypatch.setattr(
        audit_logger, "log_audit", AsyncMock(return_value=None), raising=True
    )
    monkeypatch.setattr(
        email_service,
        "send_new_order_notification",
        AsyncMock(return_value=None),
        raising=True,
    )
    monkeypatch.setattr(
        email_service,
        "send_password_reset_email",
        AsyncMock(return_value=None),
        raising=True,
    )
    yield


# ---------------------------------------------------------------------------
# Test app + HTTP client
# ---------------------------------------------------------------------------

def _build_test_app(db: AsyncIOMotorDatabase) -> FastAPI:
    """Build a minimal FastAPI app bound to the in-memory DB.

    Critical rules:
      * Never import main.py — that would trigger the real lifespan (which
        connects to MongoDB) and the MaintenanceModeMiddleware (which queries
        system_settings on every request).
      * Do not include MaintenanceModeMiddleware.
      * No lifespan / startup / shutdown hooks.
      * Routers are mounted by individual tests via app.include_router.
    """
    app = FastAPI(title="webmarket test app")

    # Override the DB-resolving dependencies so any router mounted on this
    # app uses the in-memory database, not the production singleton.
    async def _override_get_database() -> AsyncIOMotorDatabase:
        return db

    def _override_get_collection(name: str):
        return db[name]

    app.dependency_overrides[database.get_database] = _override_get_database
    app.dependency_overrides[database.get_collection] = _override_get_collection

    # Register RFC 9457 exception handlers so that ServiceError subclasses
    # propagate correctly in tests (routers no longer catch them).
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

    return app


@pytest_asyncio.fixture
async def test_app(test_db, auth_user_dep, fake_redis) -> FastAPI:
    """Minimal FastAPI app for router-level tests.

    Bypasses MaintenanceModeMiddleware and the production Database singleton
    by overriding `get_database` and `get_collection` in app.dependency_overrides.
    Also applies the default customer auth overrides and injects FakeRedis
    for lockout tests.
    """
    app = _build_test_app(test_db)
    for dep, override in auth_user_dep.items():
        app.dependency_overrides[dep] = override
    # F-017: inject fake Redis so lockout helpers work without a real server
    app.dependency_overrides[get_redis] = lambda: fake_redis
    return app


@pytest_asyncio.fixture
async def test_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client bound to the test app.

    Use with: `async with test_client as ac: response = await ac.post(...)`
    """
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
