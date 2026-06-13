# Delta Spec: normalize-error-responses

## Purpose
Global FastAPI exception handlers in `main.py` produce RFC 9457 `application/problem+json`. Zero router/service changes.

## Requirements

### Requirement: Domain Exception Normalization

System MUST register `@app.exception_handler(ServiceError)`. Response: `type` (URI), `title` (reason), `status`, `detail`, `instance` (path). HTTP status = `exception.status_code`. `Content-Type: application/problem+json`.

| Exception | Status | Code Slug |
|---|---|---|
| `NotFoundError` + subclasses | 404 | `not_found` |
| `ValidationError` + subclasses | 400 | `validation_error` |
| `InsufficientStockError` | 409 | `insufficient_stock` |
| `ConflictError` + subclasses | 409 | `conflict` |
| `ForbiddenError` | 403 | `forbidden` |
| `ShippingZoneError` + subclasses | 400 | `shipping_zone_error` |
| `InternalError` | 500 | `internal_error` |

#### Scenario: NotFoundError → 404

- **WHEN** `ProductNotFoundError` raised
- **THEN** status 404, `"type": "https://api.altotrago.com/errors/not-found"`, `"status": 404`, `"instance": "<path>"`

#### Scenario: ValidationError → 400

- **WHEN** `InvalidObjectIdError` raised
- **THEN** status 400, `"type": "https://api.altotrago.com/errors/invalid-object-id"`

#### Scenario: InsufficientStockError → 409

- **WHEN** `InsufficientStockError` raised
- **THEN** status 409, `"type": "https://api.altotrago.com/errors/insufficient-stock"`

#### Scenario: ForbiddenError → 403

- **WHEN** `ForbiddenError` raised
- **THEN** status 403, `"type": "https://api.altotrago.com/errors/forbidden"`

#### Scenario: InternalError → 500

- **WHEN** `InternalError` raised
- **THEN** status 500, `"type": "https://api.altotrago.com/errors/internal-error"`

### Requirement: Auth HTTPException Normalization

System MUST register `@app.exception_handler(HTTPException)`. 401/403 → RFC 9457, `type: about:blank`. Other codes pass through. `WWW-Authenticate` preserved.

#### Scenario: 401 → RFC 9457

- **WHEN** `HTTPException(status_code=401)` raised
- **THEN** status 401, `"type": "about:blank"`, `"title": "Unauthorized"`

#### Scenario: 403 → RFC 9457

- **WHEN** `HTTPException(status_code=403)` raised
- **THEN** status 403, `"type": "about:blank"`, `"title": "Forbidden"`

#### Scenario: 401 preserves WWW-Authenticate

- **WHEN** `HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})` raised
- **THEN** response header `WWW-Authenticate: Bearer` present

#### Scenario: Non-auth passes through

- **WHEN** `HTTPException(status_code=400)` raised
- **THEN** default FastAPI format, `Content-Type: application/json`

### Requirement: Pydantic Validation Normalization

System MUST register `@app.exception_handler(RequestValidationError)`. Status 422, `errors` array: `pointer` (RFC 6901), `detail`, `code`.

#### Scenario: Single field error

- **WHEN** missing required `product_id`
- **THEN** status 422, `"errors": [{"pointer": "/body/product_id", "detail": "field required", "code": "missing"}]`

#### Scenario: Multiple field errors

- **WHEN** `quantity` negative AND `shipping_zone` empty
- **THEN** `errors` has 2 entries with `pointer`, `detail`, `code`

#### Scenario: Content-Type correct

- **WHEN** any `RequestValidationError`
- **THEN** `Content-Type: application/problem+json`

### Requirement: type URI Construction

`type_uri(code: str) -> str` returns `https://api.altotrago.com/errors/<slug>`. Underscores → hyphens. Base URL configurable.

#### Scenario: Snake_case → hyphenated

- **WHEN** `type_uri("insufficient_stock")`
- **THEN** `"https://api.altotrago.com/errors/insufficient-stock"`

#### Scenario: Multi-word

- **WHEN** `type_uri("invalid_object_id")`
- **THEN** `"https://api.altotrago.com/errors/invalid-object-id"`

#### Scenario: Single-word

- **WHEN** `type_uri("conflict")`
- **THEN** `"https://api.altotrago.com/errors/conflict"`

### Requirement: instance from Request Path

`instance` = `request.url.path` in every RFC 9457 response.

#### Scenario: instance matches path

- **WHEN** GET `/products/abc123` raises error
- **THEN** `"instance": "/products/abc123"`

#### Scenario: Nested path

- **WHEN** POST `/cart/add` raises error
- **THEN** `"instance": "/cart/add"`

### Requirement: Cart Stock 400 Regression

Handler reads `status_code` from instance. Cart `InsufficientStockError` at 400 MUST return 400.

#### Scenario: Cart returns 400

- **WHEN** `InsufficientStockError(status_code=400)` from cart
- **THEN** HTTP 400, body `"status": 400`

### Requirement: Admin/Age-Verification Exclusion

Admin (`/admin/*`) and age-verification endpoints with own `try/except` MUST NOT be normalized.

#### Scenario: Admin not normalized

- **WHEN** admin endpoint raises `HTTPException(500)` from own handler
- **THEN** existing custom format, not RFC 9457

### Requirement: Existing Test Suite Preservation

All 48 existing tests pass. No assertion changes. Fixtures OK.

#### Scenario: Suite passes

- **WHEN** `.venv/bin/python -m pytest tests/`
- **THEN** 48 pass, exit 0

### Requirement: Handler Unit Tests

New tests cover:

| Handler | Families |
|---|---|
| `ServiceError` | NotFound, Validation, Conflict, InsufficientStock, Forbidden, ShippingZone, Internal |
| `HTTPException` | 401, 403, non-auth |
| `RequestValidationError` | single, multiple fields |

Each asserts: status, `Content-Type`, `instance`, `type`.

#### Scenario: ServiceError families covered

- **WHEN** tests run
- **THEN** one test per family, each asserting status, Content-Type, instance, type

#### Scenario: HTTPException auth + passthrough

- **WHEN** tests run
- **THEN** 401/403 → RFC 9457; non-auth → default

#### Scenario: RequestValidationError multi-field

- **WHEN** tests run
- **THEN** `errors` array with `pointer`, `detail`, `code`
