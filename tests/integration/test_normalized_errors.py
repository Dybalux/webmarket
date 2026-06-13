"""Integration tests for RFC 9457 normalized error responses.

These tests use a custom FastAPI app that registers the three global
exception handlers. A minimal test router simulates the error scenarios
that real routers would produce.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from services.exceptions import (
    ForbiddenError,
    InsufficientStockError,
    NotFoundError,
    ServiceError,
)
from utils.errors import (
    http_exception_handler,
    service_error_handler,
    validation_exception_handler,
)


# ---------------------------------------------------------------------------
# Test app fixture — fresh FastAPI with handlers registered
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_handlers() -> FastAPI:
    """FastAPI app with the three RFC 9457 handlers registered."""
    app = FastAPI(title="normalized-error-integration-tests")

    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # Mount a minimal router that can trigger each error scenario
    router = APIRouter()

    @router.get("/trigger/not-found")
    async def trigger_not_found(request: Request):
        raise NotFoundError("Producto no encontrado.")

    @router.get("/trigger/stock-409")
    async def trigger_stock_409(request: Request):
        raise InsufficientStockError("Stock insuficiente.")

    @router.get("/trigger/stock-400")
    async def trigger_stock_400(request: Request):
        raise InsufficientStockError("Stock insuficiente para carrito.", status_code=400)

    @router.get("/trigger/forbidden")
    async def trigger_forbidden(request: Request):
        raise ForbiddenError("Acceso denegado.")

    @router.post("/trigger/validation")
    async def trigger_validation(request: Request):
        # Simulate a Pydantic validation error with two fields
        raise RequestValidationError(
            errors=[
                {
                    "loc": ("body", "product_id"),
                    "msg": "field required",
                    "type": "missing",
                },
                {
                    "loc": ("body", "quantity"),
                    "msg": "ensure this value is greater than 0",
                    "type": "type_error.gt",
                },
            ]
        )

    @router.get("/trigger/auth-401")
    async def trigger_auth_401(request: Request):
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @router.get("/trigger/auth-403")
    async def trigger_auth_403(request: Request):
        raise HTTPException(status_code=403, detail="Forbidden")

    app.include_router(router)
    return app


@pytest.fixture
async def client(app_with_handlers: FastAPI):
    """Async HTTP client bound to the app with handlers."""
    transport = ASGITransport(app=app_with_handlers)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_found_returns_rfc9457(client):
    """NotFoundError → 404 with correct type URI and instance."""
    response = await client.get("/trigger/not-found")
    body = response.json()

    assert response.status_code == 404
    assert response.headers["Content-Type"] == "application/problem+json"
    assert body["type"] == "https://api.altotrago.com/errors/not-found"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["instance"] == "/trigger/not-found"
    assert body["detail"] == "Producto no encontrado."


@pytest.mark.asyncio
async def test_insufficient_stock_cart_returns_400(client):
    """Cart InsufficientStockError → 400 with RFC 9457 body."""
    response = await client.get("/trigger/stock-400")
    body = response.json()

    assert response.status_code == 400
    assert body["type"] == "https://api.altotrago.com/errors/insufficient-stock"
    assert body["title"] == "Bad Request"
    assert body["status"] == 400
    assert body["instance"] == "/trigger/stock-400"


@pytest.mark.asyncio
async def test_insufficient_stock_non_cart_returns_409(client):
    """Non-cart InsufficientStockError → 409 with RFC 9457 body."""
    response = await client.get("/trigger/stock-409")
    body = response.json()

    assert response.status_code == 409
    assert body["type"] == "https://api.altotrago.com/errors/insufficient-stock"
    assert body["title"] == "Conflict"
    assert body["status"] == 409
    assert body["instance"] == "/trigger/stock-409"


@pytest.mark.asyncio
async def test_pydantic_validation_returns_422_with_errors(client):
    """Pydantic validation → 422 with errors array containing pointer/detail/code."""
    response = await client.post("/trigger/validation")
    body = response.json()

    assert response.status_code == 422
    assert response.headers["Content-Type"] == "application/problem+json"
    assert body["type"] == "about:blank"
    assert body["title"] == "Unprocessable Entity"
    assert body["status"] == 422
    assert "errors" in body
    assert len(body["errors"]) == 2

    err0 = body["errors"][0]
    assert err0["pointer"] == "/body/product_id"
    assert err0["detail"] == "field required"
    assert err0["code"] == "missing"

    err1 = body["errors"][1]
    assert err1["pointer"] == "/body/quantity"
    assert err1["detail"] == "ensure this value is greater than 0"
    assert err1["code"] == "type_error.gt"


@pytest.mark.asyncio
async def test_auth_401_returns_rfc9457_preserves_www_authenticate(client):
    """Auth 401 → RFC 9457 with WWW-Authenticate header preserved."""
    response = await client.get("/trigger/auth-401")
    body = response.json()

    assert response.status_code == 401
    assert response.headers["Content-Type"] == "application/problem+json"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert body["type"] == "about:blank"
    assert body["title"] == "Unauthorized"
    assert body["status"] == 401
    assert body["detail"] == "Not authenticated"
    assert body["instance"] == "/trigger/auth-401"


@pytest.mark.asyncio
async def test_auth_403_returns_rfc9457(client):
    """Auth 403 → RFC 9457."""
    response = await client.get("/trigger/auth-403")
    body = response.json()

    assert response.status_code == 403
    assert response.headers["Content-Type"] == "application/problem+json"
    assert body["type"] == "about:blank"
    assert body["title"] == "Forbidden"
    assert body["status"] == 403
    assert body["instance"] == "/trigger/auth-403"
