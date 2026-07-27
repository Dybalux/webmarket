"""Integration tests for input validation (F-008, F-010).

Covers:
  - Sort-field whitelist enforcement on /admin/users and /admin/orders
  - Regex sanitization in search queries (literal match, not ReDoS)
  - Valid sort fields accepted

Uses test_client + auth_admin_dep — no real MongoDB required.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from bson import ObjectId
from httpx import AsyncClient

from models import ProductCategory, UserRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def admin_client(test_app, auth_admin_dep, test_db) -> AsyncClient:
    """Test client with admin auth and admin router mounted."""
    from routers.admin import router as admin_router
    from routers.products import router as products_router

    for dep, override in auth_admin_dep.items():
        test_app.dependency_overrides[dep] = override

    test_app.include_router(admin_router, prefix="/admin")
    test_app.include_router(products_router, prefix="/products")

    from httpx import ASGITransport
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_db(test_db):
    """Seed users and orders collections for admin listing tests."""
    users = test_db["users"]
    orders = test_db["orders"]

    await users.insert_many([
        {
            "_id": ObjectId(),
            "username": "alice",
            "email": "alice@example.com",
            "hashed_password": "hashed1",
            "role": UserRole.CUSTOMER.value,
            "age_verified": True,
            "birth_date": datetime(2000, 1, 1, tzinfo=timezone.utc),
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        },
        {
            "_id": ObjectId(),
            "username": "bob",
            "email": "bob@example.com",
            "hashed_password": "hashed2",
            "role": UserRole.ADMIN.value,
            "age_verified": True,
            "birth_date": datetime(1995, 6, 15, tzinfo=timezone.utc),
            "created_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        },
    ])

    await orders.insert_many([
        {
            "_id": ObjectId(),
            "user_id": "65f0a1b2c3d4e5f6a7b8c9d0",
            "items": [],
            "total_amount": 5000.0,
            "status": "Entregado",
            "shipping_address": {
                "street": "123 Main St",
                "city": "Springfield",
                "state": "IL",
                "zip_code": "62701",
                "country": "US",
            },
            "created_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        },
        {
            "_id": ObjectId(),
            "user_id": "65f0a1b2c3d4e5f6a7b8c9d0",
            "items": [],
            "total_amount": 2500.0,
            "status": "Pendiente",
            "shipping_address": {
                "street": "456 Elm St",
                "city": "Springfield",
                "state": "IL",
                "zip_code": "62702",
                "country": "US",
            },
            "created_at": datetime(2025, 7, 1, tzinfo=timezone.utc),
        },
    ])

    return test_db


# ---------------------------------------------------------------------------
# Sort Whitelist Tests (F-010)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAdminUsersSortWhitelist:
    """GET /admin/users — sort_by whitelist enforcement."""

    async def test_valid_sort_field_accepted(
        self, admin_client: AsyncClient, seeded_db
    ):
        """sort_by=username → 200."""
        resp = await admin_client.get("/admin/users", params={"sort_by": "username"})
        assert resp.status_code == 200

    async def test_invalid_sort_field_rejected(
        self, admin_client: AsyncClient, seeded_db
    ):
        """sort_by=password_hash → 400."""
        resp = await admin_client.get("/admin/users", params={"sort_by": "password_hash"})
        assert resp.status_code == 400
        body = resp.json()
        assert "invalid sort field" in body["detail"].lower()

    async def test_default_sort_by_accepted(
        self, admin_client: AsyncClient, seeded_db
    ):
        """No sort_by param → default (created_at) → 200."""
        resp = await admin_client.get("/admin/users")
        assert resp.status_code == 200

    async def test_all_allowed_fields_accepted(
        self, admin_client: AsyncClient, seeded_db
    ):
        """Every field in the whitelist must be accepted."""
        for field in ("created_at", "username", "email", "role", "updated_at"):
            resp = await admin_client.get(
                "/admin/users", params={"sort_by": field}
            )
            assert resp.status_code == 200, f"sort_by={field} should be allowed"


@pytest.mark.asyncio
class TestAdminOrdersSortWhitelist:
    """GET /admin/orders — sort_by whitelist enforcement."""

    async def test_valid_sort_field_accepted(
        self, admin_client: AsyncClient, seeded_db
    ):
        """sort_by=total_amount → 200."""
        resp = await admin_client.get("/admin/orders", params={"sort_by": "total_amount"})
        assert resp.status_code == 200

    async def test_invalid_sort_field_rejected(
        self, admin_client: AsyncClient, seeded_db
    ):
        """sort_by=customer_name → 400."""
        resp = await admin_client.get("/admin/orders", params={"sort_by": "customer_name"})
        assert resp.status_code == 400
        body = resp.json()
        assert "invalid sort field" in body["detail"].lower()

    async def test_all_allowed_fields_accepted(
        self, admin_client: AsyncClient, seeded_db
    ):
        """Every field in the orders whitelist must be accepted."""
        for field in ("created_at", "total_amount", "status"):
            resp = await admin_client.get(
                "/admin/orders", params={"sort_by": field}
            )
            assert resp.status_code == 200, f"sort_by={field} should be allowed"


# ---------------------------------------------------------------------------
# Regex Sanitization Tests (F-008)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSearchRegexSanitization:
    """Search queries with regex metacharacters must be sanitized."""

    async def test_search_with_metacharacters(
        self, admin_client: AsyncClient, seeded_db
    ):
        """search=C++ → 200 (sanitized, not ReDoS)."""
        resp = await admin_client.get(
            "/admin/users", params={"search": "C++"}
        )
        assert resp.status_code == 200

    async def test_search_with_regex_specials(
        self, admin_client: AsyncClient, seeded_db
    ):
        """search=(a|b)* → 200 (sanitized)."""
        resp = await admin_client.get(
            "/admin/users", params={"search": "(a|b)*"}
        )
        assert resp.status_code == 200

    async def test_normal_search_works(
        self, admin_client: AsyncClient, seeded_db
    ):
        """search=alice → 200 with matching results."""
        resp = await admin_client.get(
            "/admin/users", params={"search": "alice"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_products_search_with_metacharacters(
        self, admin_client: AsyncClient, seeded_db
    ):
        """Products search with regex specials → 200."""
        resp = await admin_client.get(
            "/products/", params={"search": "C++"}
        )
        assert resp.status_code == 200

    async def test_products_search_normal(
        self, admin_client: AsyncClient, seeded_db
    ):
        """Products search with normal string → 200."""
        resp = await admin_client.get(
            "/products/", params={"search": "Quilmes"}
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Empty Search Skip (S1.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEmptySearchSkipsRegex:
    """When search is empty or absent, the $regex clause must be skipped."""

    async def test_no_search_param_returns_all_users(
        self, admin_client: AsyncClient, seeded_db
    ):
        """No search param → all seeded users returned (no $regex filter)."""
        resp = await admin_client.get("/admin/users")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2  # alice + bob from seeded_db

    async def test_no_search_returns_all_users_list(
        self, admin_client: AsyncClient, seeded_db
    ):
        """No search param → full user list in response body."""
        resp = await admin_client.get("/admin/users")
        assert resp.status_code == 200
        data = resp.json()
        usernames = {u["username"] for u in data["users"]}
        assert usernames == {"alice", "bob"}

    async def test_empty_search_on_products_returns_all(
        self, admin_client: AsyncClient, seeded_db
    ):
        """No search param on /products/ → all active in-stock products returned."""
        resp = await admin_client.get("/products/")
        assert resp.status_code == 200
        data = resp.json()
        # 4 seeded products, but default filter is active=True + stock>0 → 3
        assert data["meta"]["total"] == 3
