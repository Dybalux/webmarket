"""Tests for infra-hardening (PR #4): CORS, security headers, docs gating, ENV, HTTPS redirect.

conftest's test_app bypasses main.py, so middleware/full-app tests use
importlib.reload to build the real app with the correct ENV.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# 4.1 ENV required — fail-fast
# ---------------------------------------------------------------------------


class TestEnvRequired:
    """ENV unset must raise ValidationError at Settings() instantiation."""

    def test_env_unset_raises_validation_error(self, monkeypatch):
        """Settings() with no ENV in environment raises ValidationError."""
        monkeypatch.delenv("ENV", raising=False)
        # Also ensure no .env file is picked up
        import config as config_mod

        with pytest.raises(ValidationError, match="ENV"):
            config_mod.Settings(_env_file=None)


# ---------------------------------------------------------------------------
# Helpers for full-app tests (importlib.reload pattern)
# ---------------------------------------------------------------------------


def _build_real_app(env_value: str):
    """Reload config + main with a specific ENV value; return the app."""
    import config as config_mod

    with patch.dict("os.environ", {"ENV": env_value}, clear=False):
        importlib.reload(config_mod)
    import main as main_mod

    importlib.reload(main_mod)
    return main_mod.app


# ---------------------------------------------------------------------------
# 4.2 Security headers on /health
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """Every response must include the four static security headers."""

    @pytest.fixture(autouse=True)
    def _setup_app(self):
        self.app = _build_real_app("test")

    @pytest.mark.asyncio
    async def test_health_has_security_headers(self):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=self.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/health")
        assert resp.status_code == 200
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "geolocation=()" in resp.headers["Permissions-Policy"]
        assert "microphone=()" in resp.headers["Permissions-Policy"]

    @pytest.mark.asyncio
    async def test_no_hsts_when_not_production(self):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=self.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/health")
        assert "Strict-Transport-Security" not in resp.headers

    @pytest.mark.asyncio
    async def test_hsts_present_in_production(self):
        prod_app = _build_real_app("production")
        from httpx import ASGITransport, AsyncClient

        # Use https:// to avoid HTTPSRedirectMiddleware 307
        transport = ASGITransport(app=prod_app)
        async with AsyncClient(transport=transport, base_url="https://test") as ac:
            resp = await ac.get("/health")
        assert "Strict-Transport-Security" in resp.headers
        assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]


# ---------------------------------------------------------------------------
# 4.3 Docs gating
# ---------------------------------------------------------------------------


class TestDocsGating:
    """Docs endpoints must 404 in production, 200 otherwise."""

    @pytest.mark.asyncio
    async def test_docs_disabled_in_production(self):
        prod_app = _build_real_app("production")
        from httpx import ASGITransport, AsyncClient

        # Use https:// to avoid HTTPSRedirectMiddleware 307
        transport = ASGITransport(app=prod_app)
        async with AsyncClient(transport=transport, base_url="https://test") as ac:
            resp_docs = await ac.get("/docs")
            resp_redoc = await ac.get("/redoc")
        assert resp_docs.status_code == 404
        assert resp_redoc.status_code == 404

    @pytest.mark.asyncio
    async def test_docs_available_in_development(self):
        dev_app = _build_real_app("development")
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=dev_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/docs")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4.4 CORS preflight
# ---------------------------------------------------------------------------


class TestCorsPreflight:
    """CORS preflight must reflect only the locked methods/headers."""

    @pytest.fixture(autouse=True)
    def _setup_app(self):
        self.app = _build_real_app("test")

    @pytest.mark.asyncio
    async def test_preflight_allows_specific_methods_and_headers(self):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=self.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.options(
                "/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": "Authorization,Content-Type",
                },
            )
        allowed_methods = resp.headers.get("access-control-allow-methods", "")
        allowed_headers = resp.headers.get("access-control-allow-headers", "")
        for m in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]:
            assert m in allowed_methods
        for h in ["Authorization", "Content-Type", "X-Requested-With"]:
            assert h in allowed_headers


# ---------------------------------------------------------------------------
# 4.5 HTTPS redirect in production
# ---------------------------------------------------------------------------


class TestHttpsRedirect:
    """HTTP requests in production must 307 to HTTPS."""

    @pytest.mark.asyncio
    async def test_redirect_in_production(self):
        prod_app = _build_real_app("production")
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=prod_app)
        async with AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as ac:
            resp = await ac.get("/health")
        assert resp.status_code == 307
        assert resp.headers["location"].startswith("https://")

    @pytest.mark.asyncio
    async def test_no_redirect_in_development(self):
        dev_app = _build_real_app("development")
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=dev_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/health")
        assert resp.status_code == 200
