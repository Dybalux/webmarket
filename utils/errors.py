"""RFC 9457 Problem Details exception handlers for FastAPI.

Registers three global handlers:
  - ServiceError → domain exceptions mapped to status + type URI
  - HTTPException → 401/403 normalized to RFC 9457; non-auth passes through
  - RequestValidationError → Pydantic errors as RFC 9457 "errors" array
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.exceptions import ServiceError


# ---------------------------------------------------------------------------
# HTTP status code → reason phrase lookup (RFC 7231 / IANA registry)
# ---------------------------------------------------------------------------

HTTP_STATUS_PHRASES: dict[int, str] = {
    status.value: status.phrase for status in HTTPStatus
}


# ---------------------------------------------------------------------------
# type URI builder
# ---------------------------------------------------------------------------


def type_uri(code: str | None, base_url: str | None = None) -> str:
    """Return an RFC 9457 ``type`` URI derived from a domain exception code.

    Algorithm:
      1. Guard empty/None → ``about:blank``
      2. Lowercase and replace underscores with hyphens
      3. Strip non-URL-safe characters (keep only ``[a-z0-9\\-]``)
      4. If the result is empty → ``about:blank``
      5. Build ``{base_url}/{slug}`` (default base: ``https://api.altotrago.com/errors``)
    """
    if not code:
        return "about:blank"

    slug = code.replace("_", "-").lower()
    slug = "".join(ch for ch in slug if ch.isascii() and (ch.isalnum() or ch == "-"))
    slug = slug.strip("-")

    if not slug:
        return "about:blank"

    if base_url is None:
        base_url = "https://api.altotrago.com/errors"

    return f"{base_url}/{slug}"


# ---------------------------------------------------------------------------
# Pydantic loc → JSON Pointer (RFC 6901)
# ---------------------------------------------------------------------------


def _loc_to_pointer(loc: tuple) -> str:
    """Convert a Pydantic ``loc`` tuple to an RFC 6901 JSON Pointer string.

    Examples:
        ("body", "product_id") → "/body/product_id"
        ("body", 0, "items") → "/body/0/items"
        () → "/"
    """
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(str(item))
        else:
            parts.append(item)
    return "/" + "/".join(parts)


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


async def service_error_handler(
    request: Request, exc: ServiceError
) -> JSONResponse:
    """Translate domain ServiceError subclasses to RFC 9457 problem+json."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": type_uri(exc.code),
            "title": HTTP_STATUS_PHRASES.get(exc.status_code, "Unknown"),
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": request.url.path,
        },
        headers={"Content-Type": "application/problem+json"},
    )


async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Normalize auth 401/403 to RFC 9457; pass-through for all others.

    Admin and age-verification paths are excluded and pass through
    to the default FastAPI handler.
    """
    # Exclusion: admin and age-verification pass through
    if request.url.path.startswith(("/admin", "/age-verification")):
        raise exc

    # Only normalize 401/403
    if exc.status_code not in (401, 403):
        raise exc

    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "type": "about:blank",
            "title": HTTP_STATUS_PHRASES.get(exc.status_code, "Unauthorized"),
            "status": exc.status_code,
            "detail": exc.detail or "",
            "instance": request.url.path,
        },
        headers={"Content-Type": "application/problem+json"},
    )

    # Preserve headers from the original exception (e.g. WWW-Authenticate)
    if exc.headers:
        for key, value in exc.headers.items():
            response.headers[key] = value

    return response


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Convert Pydantic validation errors to RFC 9457 problem+json.

    Transforms Pydantic's ``loc`` tuples to RFC 6901 JSON Pointers
    and includes ``details`` and ``code`` for each error.
    """
    errors: list[dict] = []
    for error in exc.errors():
        errors.append(
            {
                "pointer": _loc_to_pointer(error.get("loc", ())),
                "detail": error.get("msg", "Validation error"),
                "code": error.get("type", "validation_error"),
            }
        )

    return JSONResponse(
        status_code=422,
        content={
            "type": "about:blank",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": "Request validation failed",
            "instance": request.url.path,
            "errors": errors,
        },
        headers={"Content-Type": "application/problem+json"},
    )
