"""Integration tests for admin-facing stats endpoints.

These tests mount the admin router on the minimal test app and assert
the shape of the JSON returned by /admin/stats. The current admin
endpoint computes `low_stock` as the count of products with stock < 10
(hardcoded threshold in routers/admin.py line 76).

Tests are marked @pytest.mark.integration. T2.9 (module-level marker)
is applied at the bottom of this file.
"""

from __future__ import annotations

import pytest
from bson import ObjectId
from fastapi import FastAPI
from httpx import AsyncClient

from routers import admin as admin_router
from models import ProductCategory


def _mount_admin(test_app: FastAPI) -> None:
    test_app.include_router(admin_router.router)


# ---------------------------------------------------------------------------
# T2.8 — Admin low-stock count
# ---------------------------------------------------------------------------


class TestAdminLowStockCount:
    @pytest.mark.integration
    async def test_stats_counts_low_stock_products(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """Seed N products with stock < 10, hit /admin/stats, assert low_stock == N.

        The conftest pre-seeds 4 products:
          - Quilmes 1L      stock=20
          - Stella Artois   stock=5    (low)
          - Fernet Branca   stock=0    (low)
          - Vino Malbec     stock=12

        So the pre-existing low-stock count is 2. We add 3 more
        low-stock products and assert low_stock == 5.
        """
        products = test_db["products"]

        # Add 3 fresh low-stock products.
        new_ids = []
        for i, stock in enumerate([3, 7, 1]):
            oid = ObjectId()
            await products.insert_one(
                {
                    "_id": oid,
                    "name": f"Low-Stock Beer {i}",
                    "description": f"test fixture {i}",
                    "price": 1000.0 + i,
                    "category": ProductCategory.BEER.value,
                    "stock": stock,
                    "image_url": f"https://example.com/lsb{i}.jpg",
                    "abv": 4.5,
                    "volume_ml": 500,
                    "origin": "Argentina",
                    "active": True,
                }
            )
            new_ids.append(oid)

        # Pre-condition: the seeded 4 + our 3 = 7 products total.
        total = await products.count_documents({})
        assert total == 7

        # Pre-condition: low-stock count is exactly 5 (Stella, Fernet, + 3 new).
        pre = await products.count_documents({"stock": {"$lt": 10}})
        assert pre == 5

        _mount_admin(test_app)
        for dep, override in auth_admin_dep.items():
            test_app.dependency_overrides[dep] = override

        response = await test_client.get("/stats")
        assert response.status_code == 200, response.text
        body = response.json()

        # The endpoint reports products.low_stock as the count of stock<10.
        assert body["products"]["low_stock"] == 5
        # Total products should be 7 (4 seeded + 3 new).
        assert body["products"]["total"] == 7

    @pytest.mark.integration
    async def test_stats_reports_zero_low_stock_when_all_above_threshold(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """Bump every seeded product to stock=20 → low_stock must drop to 0."""
        products = test_db["products"]

        # Force all products to stock=20.
        await products.update_many({}, {"$set": {"stock": 20}})

        _mount_admin(test_app)
        for dep, override in auth_admin_dep.items():
            test_app.dependency_overrides[dep] = override

        response = await test_client.get("/stats")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["products"]["low_stock"] == 0
        # Total unchanged.
        assert body["products"]["total"] == 4


# ---------------------------------------------------------------------------
# T2.9 — Module-level integration marker
# ---------------------------------------------------------------------------

# Apply the integration marker to every test in this module.
# pytest will pick this up as the default marks for every test class.
pytestmark = pytest.mark.integration
