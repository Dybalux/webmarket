"""Integration tests for the product listing filter.

These tests mount the products router on the minimal test app and
hit GET /products via httpx. They verify the
`include_out_of_stock` query parameter contract.

  T2.7a — default GET /products/ excludes zero-stock SKUs
  T2.7b — GET /products/?include_out_of_stock=true includes zero-stock SKUs

Both tests marked @pytest.mark.integration. The admin override is
applied for the include_out_of_stock case (the query param is
documented as "for administrators") but the default-filter case uses
the regular user override (the endpoint is public).

Production code untouched.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from routers import products as products_router


def _mount_products_app(test_app: FastAPI) -> None:
    """Mount the products router on the test app.

    The pricing_settings router is no longer needed here — the
    refactored products router uses services.pricing.get_adjusted_price
    which reads from db["pricing_settings"] through the already-
    overridden get_database dependency.
    """
    test_app.include_router(products_router.router)


# ---------------------------------------------------------------------------
# T2.7 — Product filter (out-of-stock hidden by default, visible for admin)
# ---------------------------------------------------------------------------


class TestProductsOutOfStockFilter:
    @pytest.mark.integration
    async def test_default_filter_excludes_zero_stock(
        self, test_app, test_db, test_client, auth_user_dep
    ):
        """GET /products/ (no params) must NOT include the stock=0 SKU (Fernet Branca).

        The router is mounted on a path prefix when the app starts. Since
        we mount the bare router on the test app root, the path is
        GET `/`. The router does NOT require auth, but the conftest
        applies the user override anyway — that's harmless.
        """
        _mount_products_app(test_app)
        for dep, override in auth_user_dep.items():
            test_app.dependency_overrides[dep] = override

        response = await test_client.get("/")
        assert response.status_code == 200, response.text
        body = response.json()
        names = [p["name"] for p in body["items"]]

        assert "Fernet Branca 750ml" not in names, (
            "Fernet Branca has stock=0 and must be hidden by default"
        )
        # The in-stock SKUs must be present.
        for expected in ("Quilmes 1L", "Stella Artois 1L", "Vino Malbec 750ml"):
            assert expected in names

    @pytest.mark.integration
    async def test_include_out_of_stock_flag_returns_zero_stock(
        self, test_app, test_db, test_client, auth_admin_dep
    ):
        """GET /products/?include_out_of_stock=true must INCLUDE Fernet Branca (stock=0).

        The flag is meant for admins. We mount the admin auth override.
        """
        _mount_products_app(test_app)
        for dep, override in auth_admin_dep.items():
            test_app.dependency_overrides[dep] = override

        response = await test_client.get("/?include_out_of_stock=true")
        assert response.status_code == 200, response.text
        body = response.json()
        names = [p["name"] for p in body["items"]]

        assert "Fernet Branca 750ml" in names, (
            "With include_out_of_stock=true, the zero-stock SKU must appear"
        )
        # The total count must equal the seeded 4 products.
        assert body["meta"]["total"] == 4
