"""Unit tests for RFC 9457 utilities and handlers.

Covers:
  - type_uri() builder (8 edge cases)
  - _loc_to_pointer() helper (5 cases)
  - service_error_handler (7 exception families)
  - http_exception_handler (5 scenarios: auth + passthrough + admin exclusion)
  - validation_exception_handler (3 scenarios)
  - InsufficientStockError constructor patch verification (2 cases)
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock

from fastapi import Request
from utils.errors import type_uri, _loc_to_pointer


# ============================================================================
# Helper — build a mock Starlette Request
# ============================================================================


def _mock_request(path: str = "/test/endpoint") -> Request:
    """Return an ASGI Request with the given URL path."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
    }
    return Request(scope)


# ============================================================================
# type_uri() tests — Task 1.3 (RED) → 1.4 (GREEN)
# ============================================================================

TYPE_URI_CASES = [
    # (code, base_url, expected)
    ("insufficient_stock", None, "https://api.altotrago.com/errors/insufficient-stock"),
    ("invalid_object_id", None, "https://api.altotrago.com/errors/invalid-object-id"),
    ("conflict", None, "https://api.altotrago.com/errors/conflict"),
    ("", None, "about:blank"),
    (None, None, "about:blank"),
    ("café_error", None, "https://api.altotrago.com/errors/caf-error"),
    ("already-hyphenated", None, "https://api.altotrago.com/errors/already-hyphenated"),
    ("insufficient_stock", "https://example.com/errors", "https://example.com/errors/insufficient-stock"),
]


@pytest.mark.parametrize("code,base_url,expected", TYPE_URI_CASES)
def test_type_uri_parametrized(code, base_url, expected):
    """type_uri() produces correct RFC 9457 type field values."""
    result = type_uri(code, base_url) if base_url else type_uri(code)
    assert result == expected


# ============================================================================
# _loc_to_pointer() tests — Task 1.5 (RED) → 1.6 (GREEN)
# ============================================================================

LOC_TO_POINTER_CASES = [
    # (loc_tuple, expected_pointer)
    (("body", "product_id"), "/body/product_id"),
    (("body", 0, "items"), "/body/0/items"),
    ((), "/"),
    (("body",), "/body"),
    (("query", "page"), "/query/page"),
]


@pytest.mark.parametrize("loc,expected", LOC_TO_POINTER_CASES)
def test_loc_to_pointer_parametrized(loc, expected):
    """_loc_to_pointer() converts Pydantic loc tuples to RFC 6901 JSON Pointers."""
    result = _loc_to_pointer(loc)
    assert result == expected


# ============================================================================
# InsufficientStockError constructor patch — Task 1.8
# ============================================================================


def test_insufficient_stock_ctor_default():
    """InsufficientStockError default status_code is 409."""
    from services.exceptions import InsufficientStockError
    exc = InsufficientStockError()
    assert exc.status_code == 409
    assert exc.code == "insufficient_stock"


def test_insufficient_stock_ctor_override():
    """InsufficientStockError accepts status_code override to 400."""
    from services.exceptions import InsufficientStockError
    exc = InsufficientStockError("Custom detail", status_code=400)
    assert exc.status_code == 400
    assert exc.code == "insufficient_stock"


# ============================================================================
# service_error_handler tests — Task 2.1 (RED) → 2.2 (GREEN)
# ============================================================================

SERVICE_ERROR_FAMILIES = [
    # (exception, expected_status, expected_title, expected_code_slug)
    ("NotFoundError", 404, "Not Found", "not-found"),
    ("InvalidObjectIdError", 400, "Bad Request", "invalid-object-id"),
    ("InsufficientStockError", 409, "Conflict", "insufficient-stock"),
    ("ConflictError", 409, "Conflict", "conflict"),
    ("ForbiddenError", 403, "Forbidden", "forbidden"),
    ("ShippingZoneError", 400, "Bad Request", "shipping-zone-error"),
    ("InternalError", 500, "Internal Server Error", "internal-error"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc_class_name,expected_status,expected_title,expected_slug",
    SERVICE_ERROR_FAMILIES,
)
async def test_service_error_handler_families(
    exc_class_name, expected_status, expected_title, expected_slug
):
    """Each ServiceError family produces correct RFC 9457 response."""
    import services.exceptions as exc_mod
    from utils.errors import service_error_handler

    exc_class = getattr(exc_mod, exc_class_name)
    exc = exc_class() if exc_class_name != "InvalidObjectIdError" else exc_class("ID inválido.")
    request = _mock_request("/api/v1/products/abc123")

    response = await service_error_handler(request, exc)

    body = json.loads(response.body)
    assert response.status_code == expected_status
    assert response.headers["Content-Type"] == "application/problem+json"
    assert body["type"] == f"https://api.altotrago.com/errors/{expected_slug}"
    assert body["status"] == expected_status
    assert body["title"] == expected_title
    assert body["instance"] == "/api/v1/products/abc123"
    assert "detail" in body


# ============================================================================
# http_exception_handler tests — Task 2.3 (RED) → 2.4 (GREEN)
# ============================================================================


@pytest.mark.asyncio
async def test_http_exception_401_becomes_rfc9457():
    """401 → RFC 9457 with type: about:blank."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(status_code=401, detail="Not authenticated")
    request = _mock_request("/api/v1/orders/me")

    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.status_code == 401
    assert response.headers["Content-Type"] == "application/problem+json"
    assert body["type"] == "about:blank"
    assert body["title"] == "Unauthorized"
    assert body["status"] == 401
    assert body["detail"] == "Not authenticated"
    assert body["instance"] == "/api/v1/orders/me"


@pytest.mark.asyncio
async def test_http_exception_403_becomes_rfc9457():
    """403 → RFC 9457 with type: about:blank."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(status_code=403, detail="Forbidden")
    request = _mock_request("/api/v1/admin/users")

    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.status_code == 403
    assert body["type"] == "about:blank"
    assert body["title"] == "Forbidden"


@pytest.mark.asyncio
async def test_http_exception_401_preserves_www_authenticate():
    """401 with WWW-Authenticate header preserves it in the response."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(
        status_code=401,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    request = _mock_request("/api/v1/secure")

    response = await http_exception_handler(request, exc)

    assert response.headers.get("WWW-Authenticate") == "Bearer"
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_http_exception_non_auth_passes_through():
    """Non-auth 400 returns default FastAPI JSON envelope (status preserved, application/json)."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(status_code=400, detail="Bad request")
    request = _mock_request("/api/v1/products")

    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.status_code == 400
    assert response.headers["Content-Type"] == "application/json"
    assert body == {"detail": "Bad request"}


@pytest.mark.asyncio
async def test_http_exception_admin_path_excluded():
    """Admin path returns default FastAPI JSON envelope (preserves exc.headers)."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(
        status_code=401,
        detail="Unauthorized admin",
        headers={"WWW-Authenticate": "Bearer"},
    )
    request = _mock_request("/admin/stats")

    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.status_code == 401
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    assert body == {"detail": "Unauthorized admin"}


# ============================================================================
# validation_exception_handler tests — Task 2.5 (RED) → 2.6 (GREEN)
# ============================================================================


def _make_validation_error(errors_spec: list[dict]) -> "RequestValidationError":
    """Build a RequestValidationError with the given error entries.

    Each entry: {"loc": ("body", "field"), "msg": "...", "type": "..."}
    """
    from fastapi.exceptions import RequestValidationError
    from pydantic import ValidationError as _PydanticValidationError

    # Build a raw Pydantic error list that matches what FastAPI would produce
    return RequestValidationError(errors=errors_spec)


@pytest.mark.asyncio
async def test_validation_exception_single_field():
    """Single field error → one entry in errors array."""
    from utils.errors import validation_exception_handler

    exc = _make_validation_error([
        {
            "loc": ("body", "product_id"),
            "msg": "field required",
            "type": "missing",
        },
    ])
    request = _mock_request("/api/v1/products/")

    response = await validation_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.status_code == 422
    assert response.headers["Content-Type"] == "application/problem+json"
    assert body["type"] == "about:blank"
    assert body["title"] == "Unprocessable Entity"
    assert body["status"] == 422
    assert body["instance"] == "/api/v1/products/"
    assert "errors" in body
    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["pointer"] == "/body/product_id"
    assert err["detail"] == "field required"
    assert err["code"] == "missing"


@pytest.mark.asyncio
async def test_validation_exception_multiple_fields():
    """Multiple field errors → two entries with correct pointers."""
    from utils.errors import validation_exception_handler

    exc = _make_validation_error([
        {
            "loc": ("body", "quantity"),
            "msg": "ensure this value is greater than 0",
            "type": "type_error.gt",
        },
        {
            "loc": ("body", "shipping_zone"),
            "msg": "field required",
            "type": "missing",
        },
    ])
    request = _mock_request("/api/v1/orders/")

    response = await validation_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.status_code == 422
    assert len(body["errors"]) == 2
    assert body["errors"][0]["pointer"] == "/body/quantity"
    assert body["errors"][1]["pointer"] == "/body/shipping_zone"


@pytest.mark.asyncio
async def test_validation_exception_content_type():
    """Validation handler always returns Content-Type: application/problem+json."""
    from utils.errors import validation_exception_handler

    exc = _make_validation_error([
        {
            "loc": ("body", "name"),
            "msg": "field required",
            "type": "missing",
        },
    ])
    request = _mock_request("/api/v1/products/")

    response = await validation_exception_handler(request, exc)

    assert response.status_code == 422
    assert response.headers["Content-Type"] == "application/problem+json"


# ============================================================================
# F1 — Content-Type override guard in exc.headers (Judgment Day Round 2)
# ============================================================================


@pytest.mark.asyncio
async def test_http_exception_auth_branch_guards_content_type_override():
    """Auth 401 branch: exc.headers['content-type'] must NOT overwrite RFC 9457 CT."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"content-type": "text/plain", "WWW-Authenticate": "Bearer"},
    )
    request = _mock_request("/api/v1/orders/me")

    response = await http_exception_handler(request, exc)

    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_http_exception_passthrough_branch_guards_content_type_override():
    """Non-auth 400 passthrough: exc.headers['content-type'] must NOT overwrite application/json."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(
        status_code=400,
        detail="Bad request",
        headers={"content-type": "text/plain"},
    )
    request = _mock_request("/api/v1/products")

    response = await http_exception_handler(request, exc)

    assert response.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_http_exception_admin_exclusion_branch_guards_content_type_override():
    """Admin exclusion: exc.headers['content-type'] must NOT overwrite application/json."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(
        status_code=401,
        detail="Unauthorized admin",
        headers={"content-type": "text/plain", "WWW-Authenticate": "Bearer"},
    )
    request = _mock_request("/admin/stats")

    response = await http_exception_handler(request, exc)

    assert response.headers["content-type"] == "application/json"
    assert response.headers.get("WWW-Authenticate") == "Bearer"


# ============================================================================
# F2 — Tightened admin/age-verification path matching (Judgment Day Round 2)
# ============================================================================


@pytest.mark.asyncio
async def test_http_exception_admin_panel_path_not_excluded():
    """/admin-panel/foo must NOT take admin exclusion — returns RFC 9457 for 401."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(status_code=401, detail="Not authenticated")
    request = _mock_request("/admin-panel/foo")

    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.headers["content-type"] == "application/problem+json"
    assert body["type"] == "about:blank"
    assert body["title"] == "Unauthorized"


@pytest.mark.asyncio
async def test_http_exception_age_verification_panel_path_not_excluded():
    """/age-verification-panel/foo must NOT take admin exclusion — returns RFC 9457 for 403."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(status_code=403, detail="Forbidden")
    request = _mock_request("/age-verification-panel/foo")

    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.headers["content-type"] == "application/problem+json"
    assert body["type"] == "about:blank"
    assert body["title"] == "Forbidden"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/admin", "/admin/foo", "/admin/foo/bar", "/age-verification", "/age-verification/foo"],
)
async def test_http_exception_exact_admin_paths_still_excluded(path):
    """Exact matches and sub-paths of /admin and /age-verification MUST still be excluded."""
    from fastapi import HTTPException
    from utils.errors import http_exception_handler

    exc = HTTPException(status_code=401, detail="Unauthorized")
    request = _mock_request(path)

    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)

    assert response.headers["content-type"] == "application/json"
    assert body == {"detail": "Unauthorized"}


# ============================================================================
# service_error_handler detail-fallback test — Judgment Day F4
# ============================================================================


@pytest.mark.asyncio
async def test_service_error_handler_detail_fallback_when_none():
    """ServiceError with detail=None must produce 'An error occurred' fallback."""
    from services.exceptions import ServiceError
    from utils.errors import service_error_handler

    exc = ServiceError.__new__(ServiceError)  # bypass __init__ defaults
    Exception.__init__(exc, "An error occurred")
    exc.status_code = 500
    exc.code = "internal_error"
    exc.detail = None  # explicitly None — malformed subclass scenario

    request = _mock_request("/api/v1/some/path")

    response = await service_error_handler(request, exc)
    body = json.loads(response.body)

    assert response.status_code == 500
    assert body["detail"] == "An error occurred"
