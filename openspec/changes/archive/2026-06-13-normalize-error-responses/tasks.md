# Tasks: Normalize Error Responses (RFC 9457)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~310 (250 additions + 60 deletions) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Test Execution Matrix

| Task | Depends on | Gated by |
|------|-----------|----------|
| 1.1 | — | — |
| 1.2 | 1.1 | — |
| 1.3 | 1.2 (skeleton exists) | — |
| 1.4 | 1.3 (tests written) | 1.3 RED |
| 1.5 | 1.2 | — |
| 1.6 | 1.5 (tests written) | 1.5 RED |
| 1.7 | — | — |
| 1.8 | 1.7 (patch applied) | — |
| 1.9 | 1.2 (handlers exist as stubs) | — |
| 2.1 | 1.4 (type_uri works) | — |
| 2.2 | 2.1 (tests written) | 2.1 RED |
| 2.3 | 1.4 (type_uri works) | — |
| 2.4 | 2.3 (tests written) | 2.3 RED |
| 2.5 | 1.6 (_loc_to_pointer works) | — |
| 2.6 | 2.5 (tests written) | 2.5 RED |
| 3.1–3.7 | 1.7 (patch), 1.9 (handlers registered) | Suite green after each |
| 4.1 | 3.7 (all routers updated) | — |
| 5.1–5.4 | 4.1 (integration tests written) | All prior phases green |

## Out-of-Scope Anchors

- No repository layer changes
- No service refactor (except the 3-line `InsufficientStockError` patch)
- No auth logic changes
- No i18n or localized messages
- No frontend changes (escabi-frontend migration tracked separately)
- Cart 400 preserved (not aligned to 409)
- Admin/age-verification endpoints excluded from normalization

---

## Phase 1: Infrastructure Setup

### 1.1 Create `utils/__init__.py` [x]
- **Action**: Create empty `utils/__init__.py` to make `utils` a Python package
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/utils/__init__.py`
- **LOC estimate**: 2
- **Verification**: `python -c "import utils"` exits 0
- **Spec/design reference**: Design §File Structure
- **TDD step**: N/A (infrastructure)
- **Acceptance criteria**: `utils` is importable as a package

### 1.2 Create `utils/errors.py` skeleton [x]
- **Action**: Create `utils/errors.py` with imports (`Request`, `JSONResponse`, `ServiceError`, `HTTPException`, `RequestValidationError`, `http.HTTPStatus`), `HTTP_STATUS_PHRASES` dict, `type_uri()` stub returning `"about:blank"`, `_loc_to_pointer()` stub returning `"/"`, and three handler stubs returning `JSONResponse(status_code=501)`
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/utils/errors.py`
- **LOC estimate**: 30
- **Verification**: `python -c "from utils.errors import type_uri, service_error_handler, http_exception_handler, validation_exception_handler"` exits 0
- **Spec/design reference**: Design §1–§4
- **TDD step**: N/A (skeleton for TDD)
- **Acceptance criteria**: All 4 symbols importable; no syntax errors

### 1.3 Write unit tests for `type_uri()` (TDD RED) [x]
- **Action**: Create `tests/unit/test_problem_details.py` with 8 parametrized tests for `type_uri()`: `"insufficient_stock"` → hyphenated, `"invalid_object_id"` → hyphenated, `"conflict"` → single-word, `""` → `"about:blank"`, `None` → `"about:blank"`, `"café_error"` → strips accents, custom `base_url` override, already-hyphenated input preserved
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/tests/unit/test_problem_details.py`
- **LOC estimate**: 20
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k type_uri` → 8 FAIL (RED)
- **Spec/design reference**: Spec REQ-4 (3 scenarios), Design §1 (8 edge cases)
- **TDD step**: 1 (RED)
- **Acceptance criteria**: 8 tests written, all failing with stub implementation

### 1.4 Implement `type_uri()` (TDD GREEN) [x]
- **Action**: Implement `type_uri(code, base_url=None)` per Design §1 algorithm: guard empty/None → `"about:blank"`, slugify `_` → `-`, strip non-URL-safe chars, default base URL `https://api.altotrago.com/errors`, return formatted URI
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/utils/errors.py`
- **LOC estimate**: 12
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k type_uri -v` → 8 PASS
- **Spec/design reference**: Spec REQ-4, Design §1
- **TDD step**: 1 (GREEN)
- **Acceptance criteria**: All 8 `type_uri` tests pass

### 1.5 Write unit tests for `_loc_to_pointer()` (TDD RED) [x]
- **Action**: Add 5 parametrized tests: `("body", "product_id")` → `"/body/product_id"`, `("body", 0, "items")` → `"/body/0/items"` (array index), `()` → `"/"`, `("body",)` → `"/body"`, `("query", "page")` → `"/query/page"`
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/tests/unit/test_problem_details.py`
- **LOC estimate**: 12
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k loc_to_pointer` → 5 FAIL (RED)
- **Spec/design reference**: Spec REQ-3, Design §4 (edge cases)
- **TDD step**: 2 (RED)
- **Acceptance criteria**: 5 tests written, all failing with stub

### 1.6 Implement `_loc_to_pointer()` (TDD GREEN) [x]
- **Action**: Implement per Design §4: iterate loc tuple, convert ints to str, join with `/`, prefix with `/`
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/utils/errors.py`
- **LOC estimate**: 8
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k loc_to_pointer -v` → 5 PASS
- **Spec/design reference**: Spec REQ-3, Design §4
- **TDD step**: 2 (GREEN)
- **Acceptance criteria**: All 5 `_loc_to_pointer` tests pass

### 1.7 Patch `InsufficientStockError.__init__` (Option A) [x]
- **Action**: Extend `InsufficientStockError.__init__` in `services/exceptions.py` to accept `status_code: int = 409` and `code: str = "insufficient_stock"` as optional kwargs, forwarding both to `super().__init__()`
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/services/exceptions.py` (lines 108–109)
- **LOC estimate**: +3
- **Verification**: `python -c "from services.exceptions import InsufficientStockError; e = InsufficientStockError('test', status_code=400); assert e.status_code == 400"` exits 0
- **Spec/design reference**: Spec REQ-6, Design §Technical Approach (Option A)
- **TDD step**: N/A (prerequisite for cart router change)
- **Acceptance criteria**: Default 409 preserved; override to 400 works; backward compatible

### 1.8 Write unit test for constructor patch [x]
- **Action**: Add 2 tests: default `InsufficientStockError()` has `status_code=409`, `InsufficientStockError(status_code=400)` has `status_code=400`
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/tests/unit/test_problem_details.py`
- **LOC estimate**: 8
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k insufficient_stock_ctor -v` → 2 PASS
- **Spec/design reference**: Spec REQ-6, Design §Technical Approach
- **TDD step**: N/A (verification)
- **Acceptance criteria**: Both tests pass; confirms backward compatibility

### 1.9 Register 3 handlers in `main.py` [x]
- **Action**: Add imports for 3 handlers from `utils.errors` and register via `app.add_exception_handler()` in order: `ServiceError`, `HTTPException`, `RequestValidationError`
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/main.py`
- **LOC estimate**: +15
- **Verification**: `.venv/bin/python -c "from main import app; print('OK')"` exits 0; `.venv/bin/python -m pytest tests/` → 48 PASS (no regressions)
- **Spec/design reference**: Spec REQ-1, REQ-2, REQ-3; Design §Handler Registration Order
- **TDD step**: 6
- **Acceptance criteria**: App starts; all 48 existing tests pass; handlers registered

---

## Phase 2: Handler Implementation (TDD)

### 2.1 Write unit tests for `service_error_handler` (TDD RED) [x]
- **Action**: Add 7 tests mocking `Request` + each exception family: `NotFoundError` (404), `InvalidObjectIdError` (400), `InsufficientStockError` (409), `ConflictError` (409), `ForbiddenError` (403), `ShippingZoneError` (400), `InternalError` (500). Each asserts: status code, `Content-Type: application/problem+json`, `type` URI, `instance` from mock path, `title` matches reason phrase
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/tests/unit/test_problem_details.py`
- **LOC estimate**: 35
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k service_error` → 7 FAIL (RED)
- **Spec/design reference**: Spec REQ-1 (5 scenarios), REQ-7 (handler unit tests); Design §2
- **TDD step**: 3 (RED)
- **Acceptance criteria**: 7 tests written, all failing with stub handler

### 2.2 Implement `service_error_handler` (TDD GREEN) [x]
- **Action**: Implement per Design §2 pseudocode: read `exc.status_code`, `exc.code`, `exc.detail`; build RFC 9457 JSON with `type_uri(exc.code)`, `HTTP_STATUS_PHRASES[status]`, `instance=request.url.path`; return `JSONResponse` with `application/problem+json`
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/utils/errors.py`
- **LOC estimate**: 15
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k service_error -v` → 7 PASS
- **Spec/design reference**: Spec REQ-1, Design §2
- **TDD step**: 3 (GREEN)
- **Acceptance criteria**: All 7 handler tests pass; correct status, type, title, instance, Content-Type

### 2.3 Write unit tests for `http_exception_handler` (TDD RED) [x]
- **Action**: Add 5 tests: 401 → RFC 9457 with `type: about:blank`, 403 → RFC 9457, 401 with `WWW-Authenticate` header preserved, non-auth 400 → raises exc (pass-through), admin path `/admin/stats` → raises exc (exclusion)
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/tests/unit/test_problem_details.py`
- **LOC estimate**: 25
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k http_exception` → 5 FAIL (RED)
- **Spec/design reference**: Spec REQ-2 (4 scenarios), REQ-8 (admin exclusion); Design §3
- **TDD step**: 4 (RED)
- **Acceptance criteria**: 5 tests written, all failing with stub handler

### 2.4 Implement `http_exception_handler` (TDD GREEN) [x]
- **Action**: Implement per Design §3: check path starts with `/admin` or `/age-verification` → `raise exc`; check status not in (401, 403) → `raise exc`; build RFC 9457 response with `type: about:blank`; copy `exc.headers` to response headers
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/utils/errors.py`
- **LOC estimate**: 20
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k http_exception -v` → 5 PASS
- **Spec/design reference**: Spec REQ-2, REQ-8, Design §3
- **TDD step**: 4 (GREEN)
- **Acceptance criteria**: All 5 tests pass; auth normalized, non-auth/admin pass through, WWW-Authenticate preserved

### 2.5 Write unit tests for `validation_exception_handler` (TDD RED) [x]
- **Action**: Add 3 tests: single field error → `errors` array with 1 entry (pointer, detail, code), multi-field error → 2 entries with correct pointers, confirms `Content-Type: application/problem+json` and status 422
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/tests/unit/test_problem_details.py`
- **LOC estimate**: 20
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k validation_exception` → 3 FAIL (RED)
- **Spec/design reference**: Spec REQ-3 (3 scenarios); Design §4
- **TDD step**: 5 (RED)
- **Acceptance criteria**: 3 tests written, all failing with stub handler

### 2.6 Implement `validation_exception_handler` (TDD GREEN) [x]
- **Action**: Implement per Design §4: iterate `exc.errors()`, build `errors` list with `pointer` (via `_loc_to_pointer`), `detail`, `code`; return 422 `JSONResponse` with RFC 9457 shape + `errors` array
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/utils/errors.py`
- **LOC estimate**: 18
- **Verification**: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -k validation_exception -v` → 3 PASS; full unit suite: `.venv/bin/python -m pytest tests/unit/test_problem_details.py -v` → all pass
- **Spec/design reference**: Spec REQ-3, Design §4
- **TDD step**: 5 (GREEN)
- **Acceptance criteria**: All 3 tests pass; correct 422 status, errors array with pointer/detail/code

---

## Phase 3: Router Catch-Block Removal (Mechanical)

### 3.1 Remove catch blocks from `routers/products.py` [x]
- **Action**: Remove 5 try/except blocks that catch `ServiceError` → raise `HTTPException` (lines 33-36, 95-96, 123-124, 147-148, 175-176). Let `ServiceError` propagate naturally
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/routers/products.py`
- **LOC estimate**: -10
- **Verification**: `.venv/bin/python -m pytest tests/ -v --tb=short` → 48+ PASS (no regressions)
- **Spec/design reference**: Design §Phase 3, Proposal scope (zero router logic changes)
- **TDD step**: 7
- **Acceptance criteria**: 0 try/except wrapping ServiceError in products.py; suite green

### 3.2 Remove catch blocks from `routers/inventory.py` [x]
- **Action**: Remove 2 try/except blocks (lines 44-45, 69-70)
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/routers/inventory.py`
- **LOC estimate**: -4
- **Verification**: `.venv/bin/python -m pytest tests/ -v --tb=short` → all PASS
- **Spec/design reference**: Design §Phase 3
- **TDD step**: 7
- **Acceptance criteria**: 0 try/except wrapping ServiceError; suite green

### 3.3 Remove catch blocks from `routers/orders.py` [x]
- **Action**: Remove 8 try/except blocks (lines 66-81, 122-126, 149-151, 177-178)
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/routers/orders.py`
- **LOC estimate**: -16
- **Verification**: `.venv/bin/python -m pytest tests/ -v --tb=short` → all PASS
- **Spec/design reference**: Design §Phase 3
- **TDD step**: 7
- **Acceptance criteria**: 0 try/except wrapping ServiceError; suite green

### 3.4 Remove catch blocks from `routers/payments.py` [x]
- **Action**: Remove 4 try/except blocks (lines 35-41)
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/routers/payments.py`
- **LOC estimate**: -8
- **Verification**: `.venv/bin/python -m pytest tests/ -v --tb=short` → all PASS
- **Spec/design reference**: Design §Phase 3
- **TDD step**: 7
- **Acceptance criteria**: 0 try/except wrapping ServiceError; suite green

### 3.5 Remove catch blocks from `routers/combos.py` [x]
- **Action**: Remove 6 try/except blocks (lines 116-120, 151-153, 185-186)
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/routers/combos.py`
- **LOC estimate**: -10
- **Verification**: `.venv/bin/python -m pytest tests/ -v --tb=short` → all PASS
- **Spec/design reference**: Design §Phase 3
- **TDD step**: 7
- **Acceptance criteria**: 0 try/except wrapping ServiceError; suite green

### 3.6 Remove catch blocks from `routers/pricing_settings.py` [x]
- **Action**: Remove 3 try/except blocks (lines 32-33, 57-58, 93-94)
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/routers/pricing_settings.py`
- **LOC estimate**: -6
- **Verification**: `.venv/bin/python -m pytest tests/ -v --tb=short` → all PASS
- **Spec/design reference**: Design §Phase 3
- **TDD step**: 7
- **Acceptance criteria**: 0 try/except wrapping ServiceError; suite green

### 3.7 Modify `routers/cart.py` (re-raise with status_code=400) [x]
- **Action**: Replace 2 catch blocks: change `raise HTTPException(status_code=400, detail=e.detail)` → `raise InsufficientStockError(e.detail, status_code=400)`. Add `from services.exceptions import InsufficientStockError` if not present
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/routers/cart.py` (lines 71-73, 101-103)
- **LOC estimate**: ~4 changed
- **Verification**: `.venv/bin/python -m pytest tests/ -v --tb=short` → all PASS; cart stock test still returns 400
- **Spec/design reference**: Spec REQ-6, Design §Technical Approach (cart 400 override)
- **TDD step**: 7
- **Acceptance criteria**: Cart re-raises `InsufficientStockError` with `status_code=400`; suite green

---

## Phase 4: Integration Tests

### 4.1 Create integration test fixture + 6 tests [x]
- **Action**: Create `tests/integration/__init__.py` and `tests/integration/test_normalized_errors.py`. Build a fixture `app_with_handlers` that creates a fresh FastAPI app, registers the 3 handlers, mounts a minimal test router, and provides a `TestClient`. Write 6 integration tests: NotFound→404 with correct type URI, InsufficientStock→409, Pydantic validation→422 with errors array, auth 401→RFC 9457 with WWW-Authenticate, cart InsufficientStock→400 (regression), instance matches request path
- **Files**: `/home/dybalux/Escritorio_Dev/webmarket/tests/integration/__init__.py`, `/home/dybalux/Escritorio_Dev/webmarket/tests/integration/test_normalized_errors.py`
- **LOC estimate**: 80
- **Verification**: `.venv/bin/python -m pytest tests/integration/test_normalized_errors.py -v` → 6 PASS
- **Spec/design reference**: Spec REQ-1 through REQ-9 (all scenarios end-to-end); Design §Testing Strategy
- **TDD step**: 8
- **Acceptance criteria**: 6 integration tests pass; each verifies full HTTP round-trip with correct status, Content-Type, type, instance

---

## Phase 5: Final Verification

### 5.1 Run full test suite verbose [x]
- **Action**: Run `.venv/bin/python -m pytest tests/ -v --tb=short`
- **Files**: N/A
- **LOC estimate**: 0
- **Verification**: Exit code 0; output shows ~82 tests (48 existing + ~34 new)
- **Spec/design reference**: Spec REQ-9 (48 existing pass), REQ-10 (handler tests)
- **TDD step**: N/A (verification)
- **Acceptance criteria**: All tests pass, exit 0, 0 failures, 0 errors

### 5.2 Regression check: 48 existing tests [x]
- **Action**: Confirm all original 48 tests pass with no assertion changes
- **Files**: N/A
- **LOC estimate**: 0
- **Verification**: `.venv/bin/python -m pytest tests/ --ignore=tests/integration/ --ignore=tests/unit/test_problem_details.py -v` → 48 PASS
- **Spec/design reference**: Spec REQ-9
- **TDD step**: N/A (verification)
- **Acceptance criteria**: 48 original tests pass unchanged

### 5.3 Spot-check 3 representative scenarios manually [x]
- **Action**: Use `TestClient` in a quick script to verify: (a) NotFound→404 with `type: .../not-found`, (b) InsufficientStock→409 with `type: .../insufficient-stock`, (c) Pydantic validation→422 with `errors` array containing `pointer`
- **Files**: N/A (ad-hoc verification)
- **LOC estimate**: 0
- **Verification**: Manual inspection of 3 response bodies matches Design §Data Flow examples
- **Spec/design reference**: Design §Data Flow Scenarios 1–3
- **TDD step**: N/A (verification)
- **Acceptance criteria**: 3 response bodies match expected RFC 9457 shape exactly
