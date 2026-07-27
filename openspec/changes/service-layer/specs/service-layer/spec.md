# Service Layer Specification

## Purpose

Define the behavioral contract for extracting business logic from 13 flat FastAPI routers (~4000 LOC) into a `services/` package of async function modules. This is a structural refactor with **zero behavior changes**: the HTTP API surface (paths, methods, request/response schemas, status codes, error message bodies) MUST remain byte-identical. The change ships as 4 ordered PR slices (Inventory → Pricing → Cart → Orders) plus a pre-cleanup PR #0, each ≤400 LOC.

`services/` modules receive `AsyncIOMotorDatabase` (not individual collections), raise domain exceptions from `services/exceptions.py`, and return Pydantic models or domain dicts. Routers become thin HTTP adapters: parse input → call service → translate domain exceptions to `HTTPException` → serialize.

No `repositories/` directory is introduced. Error response normalization is deferred to a future `normalize-error-responses` change. MongoDB remains on M0 (no transactions).

## Requirements

### Requirement: Service Module Shape

A new `services/` package MUST exist at the project root. It MUST contain: `__init__.py`, `exceptions.py`, `inventory.py`, `pricing.py`, `cart.py`, `combos.py`, `orders.py`, `payments.py`, `shipping.py`, `products.py`.

Each non-exceptions module MUST export async functions (not classes). Each function MUST accept `db: AsyncIOMotorDatabase` as its first data parameter (after primitive args), so services can access multiple collections for cross-cutting work.

Functions MUST raise domain exceptions from `services/exceptions.py`; they MUST NOT raise `HTTPException`. Functions MUST return Pydantic models or domain dicts; routers handle serialization.

#### Scenario: A new service module is callable from a router

- GIVEN `services/inventory.py` with `async def update_stock(db, product_id, delta)`
- WHEN a router calls it with a mock `AsyncIOMotorDatabase`
- THEN the call is awaited and returns the updated product dict
- AND no `HTTPException` is raised by the service function

#### Scenario: Service receives database, not individual collections

- GIVEN `services/orders.py` with `async def create_order(db, user_id, order_data)`
- WHEN the function needs to access `orders`, `products`, `carts`, and `combos` collections
- THEN it derives them from `db` internally (`db.orders`, `db.products`, etc.)
- AND the caller does NOT pass individual collection objects

#### Scenario: Service returns a Pydantic model

- GIVEN `services/pricing.py` with `async def get_adjusted_price(db, base_price)`
- WHEN the function computes the adjusted price
- THEN it returns a Pydantic model or a plain value (float)
- AND the router is responsible for `JSONResponse` serialization

### Requirement: Domain Exception Hierarchy

`services/exceptions.py` MUST define an exception class tree rooted at `ServiceError` (a subclass of `Exception`). It MUST include at minimum: `ServiceError`, `NotFoundError`, `InsufficientStockError`, `InvalidStateTransitionError`, `ValidationError` (domain-level, distinct from Pydantic's).

Each exception MUST carry an HTTP status code hint (e.g., `InsufficientStockError` → 409) and a stable `code` string (e.g., `"insufficient_stock"`). Routers MUST translate exceptions to `HTTPException` using the hint code, and the resulting response shape MUST be byte-identical to today's shape for the same input.

#### Scenario: InsufficientStockError maps to 409

- GIVEN `InsufficientStockError(product_id="abc", requested=10, available=3)`
- WHEN the router catches it
- THEN it raises `HTTPException(status_code=409, detail="...")` with the same `detail` string the router emits today for that condition

#### Scenario: NotFoundError maps to 404

- GIVEN `NotFoundError(resource="product", id="xyz")`
- WHEN the router catches it
- THEN it raises `HTTPException(status_code=404, detail="...")` matching the current 404 message format for that resource

#### Scenario: ValidationError maps to 400

- GIVEN `ValidationError(field="shipping_zone", message="Zona de envío inválida")`
- WHEN the router catches it
- THEN it raises `HTTPException(status_code=400, detail="...")` with the same message shape used today

#### Scenario: ServiceError is the base class

- GIVEN a custom domain exception `ComboInactiveError`
- WHEN it is defined as a subclass of `ServiceError`
- THEN it inherits the `status_code` and `code` attributes pattern
- AND routers can catch `ServiceError` as a fallback for unmapped domain exceptions

### Requirement: Router → Service Translation Contract

Each router endpoint MUST be reduced to: parse Pydantic input, call the corresponding service function, catch domain exceptions, translate to `HTTPException` with the same code/message as today, serialize the service return value.

The router MUST NOT call `get_collection(...)` directly after its corresponding service slice lands. The router MUST NOT contain business logic (no stock math, no price calculation, no combo resolution, no email triggers, no alert generation) after its corresponding service is extracted.

#### Scenario: Router no longer imports get_collection after Slice 1

- GIVEN a router for inventory endpoints (`routers/inventory.py`)
- WHEN Slice 1 (Inventory) lands
- THEN `rg "get_collection\(" routers/inventory.py` returns zero matches
- AND all collection access is delegated to `services.inventory.*` functions

#### Scenario: Router translates domain exception to HTTPException

- GIVEN `services/inventory.py` raises `NotFoundError(resource="product", id=p_id)`
- WHEN `routers/inventory.py` catches it in a `try/except` block
- THEN it raises `HTTPException(status_code=404, detail="Producto no encontrado.")`
- AND the `detail` string matches the exact text the router produced before the refactor

#### Scenario: Router contains no business logic after extraction

- GIVEN `routers/orders.py` after Slice 4 (Orders) lands
- WHEN the file is read
- THEN it contains no stock decrement logic, no combo resolution, no price calculation, no email sending
- AND its endpoints consist solely of: parse → call service → catch → translate → return

### Requirement: API 1:1 Preservation

The HTTP API surface (paths, methods, request schemas, response schemas, status codes, error message bodies) MUST be byte-identical to today's behavior. This MUST be verified for at least: `POST /orders`, `POST /cart/add`, `GET /products`, `GET /orders/me`, `PUT /orders/admin/{id}/status`, `POST /payments/webhook`.

The verification MUST be a `curl`-based smoke test captured in a `MANUAL_SMOKE.md` file in the change folder, listing each endpoint and the expected response.

#### Scenario: `curl POST /orders` returns identical body

- GIVEN a seeded order scenario (user with cart containing a product with sufficient stock)
- WHEN the smoke script runs against the running server after all slices land
- THEN the response body matches a checked-in golden file byte-for-byte
- AND the status code is 201

#### Scenario: `curl POST /cart/add` returns identical body

- GIVEN an authenticated user and a valid product with stock > 0
- WHEN the smoke script sends `POST /cart/add` with a `CartItem` payload
- THEN the response body matches the pre-refactor response
- AND the status code is 200

#### Scenario: `curl GET /products` returns identical body

- GIVEN a catalog with at least one in-stock product
- WHEN the smoke script sends `GET /products`
- THEN the response body matches the pre-refactor response
- AND out-of-stock products are excluded (same filter behavior)

#### Scenario: `curl GET /orders/me` returns identical body

- GIVEN an authenticated user with at least one order in the database
- WHEN the smoke script sends `GET /orders/me`
- THEN the response body matches the pre-refactor response
- AND the status code is 200

#### Scenario: `curl PUT /orders/admin/{id}/status` returns identical body

- GIVEN an admin user and an order in PENDING status
- WHEN the smoke script sends `PUT /orders/admin/{id}/status` with `new_status=CONFIRMED`
- THEN the response body matches the pre-refactor response
- AND the order's status is updated to CONFIRMED

#### Scenario: `curl POST /payments/webhook` returns identical body

- GIVEN a valid Mercado Pago webhook payload with correct signature
- WHEN the smoke script sends `POST /payments/webhook`
- THEN the response body matches the pre-refactor response
- AND the status code is 200

### Requirement: Test Suite Preservation

All 12 existing test files MUST continue to pass after each slice lands. Test files MAY have fixture adjustments (e.g., adding `dependency_overrides` for services) but MUST NOT have assertion or scenario changes. If a test must change beyond fixtures to make it pass, that test change MUST be called out in the PR description and reviewed as part of the slice.

#### Scenario: `pytest` exits 0 after each slice

- GIVEN the test suite at HEAD of the slice branch
- WHEN `pytest` runs
- THEN all tests pass with no errors and no new failures
- AND the exit code is 0

#### Scenario: Fixture changes do not alter test assertions

- GIVEN `tests/test_inventory.py` before and after Slice 1
- WHEN the diff is reviewed
- THEN only fixture imports or `dependency_overrides` lines changed
- AND no `assert` statements or test scenarios were modified

#### Scenario: New failure requires PR description callout

- GIVEN a test that fails after a slice due to a behavioral change (not a fixture issue)
- WHEN the PR is created
- THEN the PR description explicitly lists the test file, the changed assertion, and the reason
- AND the reviewer must approve the assertion change as part of the slice

### Requirement: Slice Delivery Contract

The change MUST ship as 4 separate PRs, merged in this order: Inventory → Pricing → Cart → Orders. A pre-cleanup PR #0 MUST land first, deleting `routers/orders_backup.py`. PR #0 is exempt from the 400-LOC budget since it is a single `git rm`.

Each slice PR MUST be ≤400 LOC of changes (`git diff --stat` on the PR branch). Each slice PR MUST leave the test suite green. Each slice PR MUST update the change's `apply-progress.md` with what landed and what remains.

#### Scenario: Slice 1 PR is under 400 LOC

- GIVEN the PR for InventoryService (Slice 1)
- WHEN `gh pr diff --stat <n>` runs
- THEN total changed lines is ≤400
- AND the PR adds `services/__init__.py`, `services/exceptions.py`, `services/inventory.py`
- AND `routers/inventory.py` is reduced in LOC

#### Scenario: Slices land in declared order

- GIVEN the PR list for the service-layer change
- WHEN ordered by merge time
- THEN the order is PR #0 → Inventory → Pricing → Cart → Orders
- AND no slice PR is merged before its predecessor

#### Scenario: Test suite is green after each slice

- GIVEN any slice PR branch
- WHEN `pytest` runs on that branch
- THEN all 12 test files pass
- AND no new failures or regressions exist

#### Scenario: apply-progress.md is updated after each slice

- GIVEN a slice PR has been merged
- WHEN the change's `apply-progress.md` is read
- THEN it records which slice landed, its LOC count, and what remains
- AND the progress reflects the current state accurately

### Requirement: Out-of-Scope Items (Explicit Non-Goals)

The change MUST NOT introduce a `repositories/` directory. The change MUST NOT normalize error response shapes. The change MUST NOT upgrade MongoDB tier to enable transactions. The change MUST NOT add new endpoints or change business behavior. The change MUST NOT split `models.py` into a package.

#### Scenario: No repositories directory exists

- GIVEN the project tree after all slices land
- WHEN `ls services/` is run
- THEN only service modules and `exceptions.py` exist
- AND no `repositories/` directory is present at the project root

#### Scenario: Error response shape is unchanged

- GIVEN a 409 response from `POST /orders` before and after the refactor
- WHEN the response bodies are compared
- THEN they are byte-identical
- AND no new error fields or wrapper objects were introduced

#### Scenario: No new endpoints added

- GIVEN the OpenAPI schema (`/openapi.json`) before and after all slices
- WHEN the endpoint lists are compared
- THEN they are identical
- AND no new paths or methods exist

#### Scenario: models.py remains a single file

- GIVEN the project root after all slices land
- WHEN `ls models.py` is run
- THEN `models.py` exists as a single file
- AND no `models/` package directory exists
