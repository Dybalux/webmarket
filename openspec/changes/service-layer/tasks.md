# Tasks: Service Layer

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1380 total (PR #0 -422, PR #1 ~160, PR #2 ~180, PR #3 ~290, PR #4 ~350) |
| 400-line budget risk | **Low** (all slices ≤400 LOC by design) |
| Chained PRs recommended | **Yes** (5 PRs by design; all respect 400 budget) |
| Suggested split | PR #0 → PR #1 → PR #2 → PR #3 → PR #4 (leaf-first by dependency graph) |
| Delivery strategy | ask-on-risk |
| Chain strategy | defer to user |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 0 | Delete dead code `orders_backup.py` | PR #0 | base = main. Trivial, -422 LOC. |
| 1 | Inventory service + exceptions + thin router | PR #1 | base = main (or PR #0 branch). Proves the pattern. |
| 2 | Pricing service + thin pricing_settings/products routers | PR #2 | base = PR #1 branch. Independent leaf. |
| 3 | Cart service + thin products/combos public routers | PR #3 | base = PR #2 branch. Largest non-order slice. |
| 4 | Orders service + payments/shipping + remaining admin routers | PR #4 | base = PR #3 branch. Most complex; depends on all prior. |

---

## Phase 0: Pre-cleanup (PR #0)

**PR target**: PR #0 — Delete dead code
**Total estimated diff**: ~-422 LOC (negative, exempt from 400 budget)
**Test files touched**: none
**MANUAL_SMOKE endpoints**: none
**Risk level**: Low

- [x] **0.1** Delete `routers/orders_backup.py` and remove any import from `main.py` (if present). Verify: `rg "orders_backup" .` returns no matches. Run `pytest` — all 12 test files still green. 📏 ~-422 LOC

---

## Phase 1: Inventory Service (PR #1)

**PR target**: PR #1 — Extract inventory logic
**Total estimated diff**: ~160 LOC
**Test files touched**: `tests/test_inventory.py`, `tests/test_inventory_alerts_integration.py`, `tests/unit/test_inventory_alerts.py`
**MANUAL_SMOKE endpoints**: `PUT /inventory/{id}/stock`, `PUT /inventory/{id}/stock/add`, `GET /inventory/alerts`
**Risk level**: Low

- [x] **1.1** Create `services/__init__.py` (empty) and `services/exceptions.py` with the full exception tree from design ADR-3 (§4): `ServiceError`, `NotFoundError`, `ValidationError`, `InsufficientStockError`, `InternalError`, and their subclasses listed in the class tree. Each exception carries `status_code`, `code`, `detail`. 📏 ~80 LOC
  - **Reference**: design §4 (class tree), spec Requirement: Domain Exception Hierarchy
  - **Verification**: `python -c "from services.exceptions import ServiceError, NotFoundError, ValidationError, InsufficientStockError; print('OK')"`

- [x] **1.2** Create `services/inventory.py` with public functions from design §2.1: `update_stock(db, product_id, new_stock, admin_user_id)`, `add_stock(db, product_id, quantity, admin_user_id)`, `get_alerts(db, limit)`. Include private `_check_and_create_alert(db, product_id)` and `_LOW_STOCK_THRESHOLD = 10`. Functions receive `AsyncIOMotorDatabase`, raise domain exceptions, return `Product` or `list[InventoryAlert]`. 📏 ~80 LOC
  - **Reference**: design §2.1, §5.3 (sequence diagram)
  - **Verification**: `python -c "from services.inventory import update_stock, add_stock, get_alerts; print('OK')"`

- [x] **1.3** Refactor `routers/inventory.py` to call services. Remove `get_products_collection`, `get_alerts_collection`, `check_and_create_alert`. Each endpoint: parse → `try/except` translating domain exceptions to `HTTPException` (identical status/message) → return service result. Use single `db = Depends(get_database)`. 📏 ~40 removed, ~40 added
  - **Reference**: design §3 (worked example), §4 (translation map rows 1-2), spec Requirement: Router → Service Translation Contract
  - **Verification**: `rg "get_collection\(" routers/inventory.py` returns zero matches

- [x] **1.4** Update test fixtures: add `dependency_overrides` for `services.inventory.update_stock`, `services.inventory.add_stock`, `services.inventory.get_alerts` where needed. **Do not change any `assert` lines** — only fixture imports or override registrations. 📏 ~20 LOC
  - **Reference**: spec Requirement: Test Suite Preservation (Scenario: Fixture changes do not alter test assertions)
  - **Verification**: `git diff tests/test_inventory.py | rg "assert"` returns zero changes

- [x] **1.5** Run full test suite: `pytest -v`. All 12 test files must pass. 📏 0 LOC
  - **Verification**: `pytest` exits 0

- [x] **1.6** Run MANUAL_SMOKE for `PUT /inventory/{id}/stock`, `PUT /inventory/{id}/stock/add`, `GET /inventory/alerts` — responses must be byte-identical to pre-refactor. 📏 0 LOC
  - **Reference**: spec Requirement: API 1:1 Preservation
  - **Verification**: `curl` against running server, compare with golden responses

- [x] **1.7** Update `openspec/changes/service-layer/apply-progress.md` with PR #1 landing report (LOC count, what landed, what remains). 📏 ~10 LOC
  - **Verification**: file exists and reflects current progress

---

## Phase 2: Pricing Service (PR #2)

**PR target**: PR #2 — Extract pricing logic
**Total estimated diff**: ~180 LOC
**Test files touched**: `tests/test_products_filter.py`
**MANUAL_SMOKE endpoints**: `GET /pricing-settings`, `GET /products`, `GET /products/{id}`
**Risk level**: Low

- [x] **2.1** Create `services/pricing.py` with public functions from design §2.2: `get_settings(db)`, `update_settings(db, update, admin_user_id)`, `get_adjusted_price(db, base_price)`. Include private `_is_active(settings, current_time)`. 📏 ~70 LOC
  - **Reference**: design §2.2
  - **Verification**: `python -c "from services.pricing import get_settings, update_settings, get_adjusted_price; print('OK')"`

- [x] **2.2** Review `services/exceptions.py` — no new exceptions needed for pricing (uses existing from Phase 1). Confirm. 📏 0 LOC
  - **Reference**: design §6 Slice 2 "New exceptions: None"

- [x] **2.3** Refactor `routers/pricing_settings.py` (if exists) to use `services.pricing.get_settings` and `services.pricing.update_settings`. Remove collection deps, add `db = Depends(get_database)`, add `try/except` translation. 📏 ~50 LOC change
  - **Reference**: design §6 Slice 2
  - **Verification**: `rg "get_collection\(" routers/pricing_settings.py` returns zero (or file does not exist)

- [x] **2.4** Refactor `routers/products.py` public endpoints (`GET /`, `GET /{id}`) to call `services.pricing.get_adjusted_price` instead of importing `pricing_helpers.get_adjusted_price` directly. Remove `get_pricing_settings_collection` import. 📏 ~30 LOC change
  - **Reference**: design §6 Slice 2
  - **Verification**: `rg "pricing_helpers" routers/products.py` returns zero for public endpoints

- [x] **2.5** Refactor `routers/combos.py` public endpoints (`GET /`, `GET /{id}`) to use `services.pricing.get_adjusted_price`. Same pattern as 2.4. 📏 ~20 LOC change
  - **Reference**: design §2.4 (combos depends on pricing)
  - **Verification**: `rg "pricing_helpers" routers/combos.py` returns zero for public endpoints

- [x] **2.6** Refactor `routers/orders.py` pricing parts only: replace `pricing_helpers.get_adjusted_price` calls with `services.pricing.get_adjusted_price`. Full order refactor is Phase 4. 📏 ~10 LOC change
  - **Reference**: design §6 Slice 2
  - **Verification**: `rg "from pricing_helpers import" routers/orders.py` returns zero

- [x] **2.7** Update fixtures in `tests/test_products_filter.py` for `dependency_overrides` on `services.pricing.*`. No assertion changes. 📏 ~15 LOC
  - **Verification**: `git diff tests/test_products_filter.py | rg "assert"` returns zero

- [x] **2.8** Run full test suite: `pytest -v`. All 12 test files must pass. 📏 0 LOC
  - **Verification**: `pytest` exits 0

- [x] **2.9** Run MANUAL_SMOKE for `GET /products` and `GET /combos` — dynamic pricing still applied, responses byte-identical. Update `apply-progress.md`. 📏 0 LOC
  - **Verification**: `curl` responses match golden files

---

## Phase 3: Cart Service (PR #3)

**PR target**: PR #3 — Extract cart logic + thin product/combo public routers
**Total estimated diff**: ~290 LOC
**Test files touched**: `tests/test_cart_stock.py`, `tests/test_products_filter.py`, `tests/test_inventory_alerts_integration.py`
**MANUAL_SMOKE endpoints**: `POST /cart/add`, `GET /cart/validate-stock`, `GET /cart/`, `DELETE /cart/clear`, `POST /cart/cleanup`, `GET /products`
**Risk level**: Medium

- [x] **3.1** Create `services/cart.py` with public functions from design §2.3: `get_cart`, `add_to_cart`, `update_cart_item`, `remove_from_cart`, `cleanup_cart`, `validate_cart_stock`, `clear_cart`. Include private helpers: `_get_or_create_cart`, `_save_cart`, `_resolve_item_type`, `_resolve_combo_components`, `_check_stock`. 📏 636 LOC (includes full enrichment logic + all 7 endpoints + consolidated helpers)
  - **Reference**: design §2.3, §5.2 (sequence diagram)
  - **Verification**: `python -c "from services.cart import get_cart, add_to_cart, update_cart_item, remove_from_cart, clear_cart, cleanup_cart, validate_cart_stock; print('OK')"`

- [x] **3.2** Create `services/products.py` with public-facing functions from design §2.8: `list_public`, `get_public`. Include `_build_product_query` and `_apply_dynamic_pricing` helpers. 📏 ~60 LOC
  - **Reference**: design §2.8
  - **Verification**: `python -c "from services.products import list_public, get_public; print('OK')"`

- [x] **3.3** Create `services/combos.py` with public-facing functions from design §2.4: `get_active`, `get_by_id`. Include `_enrich_combos`, `_bulk_load_products` helpers. 📏 ~50 LOC
  - **Reference**: design §2.4
  - **Verification**: `python -c "from services.combos import get_active, get_by_id; print('OK')"`

- [x] **3.4** Add `CartItemNotFoundError`, `ComboInactiveError` to `services/exceptions.py` (subclasses per design §4 class tree). 📏 ~15 LOC
  - **Reference**: design §4 (class tree), §6 Slice 3
  - **Verification**: `python -c "from services.exceptions import CartItemNotFoundError, ComboInactiveError; print('OK')"`

- [x] **3.5** Refactor `routers/cart.py` to call services. Eliminate the 4x stock validation duplication per design §5.2. Each endpoint: parse → `try/except` → return. Replace `get_carts_collection`, `get_products_collection` with `db = Depends(get_database)`. 📏 ~478 removed, ~124 added (net -354 LOC, 67% reduction)
  - **Reference**: design §5.2 (sequence diagram), §4 (translation map rows 3, 6-7)
  - **Verification**: `rg "get_collection\(" routers/cart.py` returns zero ✅

- [x] **3.6** Refactor `routers/products.py` public endpoints to call `services.products.list_public` and `services.products.get_public`. Admin endpoints stay for Phase 4. 📏 ~40 LOC change
  - **Reference**: design §6 Slice 3
  - **Verification**: `rg "get_collection\(" routers/products.py` returns zero for public endpoints

- [x] **3.7** Refactor `routers/combos.py` public endpoints to call `services.combos.get_active` and `services.combos.get_by_id`. Admin endpoints stay for Phase 4. 📏 ~40 LOC change
  - **Reference**: design §6 Slice 3
  - **Verification**: `rg "get_collection\(" routers/combos.py` returns zero for public endpoints

- [x] **3.8** Update fixtures in `tests/test_cart_stock.py` and any cart-related tests for `dependency_overrides` on `services.cart.*`. No assertion changes. 📏 0 LOC (no changes needed — test_app fixture already overrides `get_database` and `get_collection`)
  - **Verification**: `git diff tests/test_cart_stock.py | rg "assert"` returns zero ✅

- [x] **3.9** Run full test suite: `pytest -v`. All 12 test files must pass. 📏 0 LOC
  - **Verification**: `pytest` exits 0 ✅ (48 passed, 0 failed)

- [x] **3.10** Run MANUAL_SMOKE for `POST /cart/add` and `GET /cart/validate-stock` — byte-identical. Update `apply-progress.md`. 📏 0 LOC
  - **Verification**: `curl` responses match golden files

---

## Phase 4: Orders Service (PR #4)

**PR target**: PR #4 — Extract orders logic + remaining services
**Total estimated diff**: ~350 LOC
**Test files touched**: `tests/test_orders_stock.py`, `tests/test_admin_stats.py`
**MANUAL_SMOKE endpoints**: `POST /orders`, `GET /orders/me`, `GET /orders/{id}`, `POST /orders/{id}/select-payment-method`, `PUT /orders/admin/{id}/status`, `POST /payments/webhook`
**Risk level**: High

- [x] **4.1** Create `services/orders.py` with public functions from design §2.5: `create_order`, `get_my_orders`, `get_order_details`, `select_payment_method`, `update_status_admin`, `get_shipping_prices`. Keep ≤160 LOC by extracting private helpers: `_process_combo_item`, `_compute_shipping_cost`, `_decrement_stock_batch`, `_rollback_stock_batch`, `_build_order_items`, `_restock_order_items`. Preserve `$gte` guard + rollback pattern. 📏 ~160 LOC
  - **Reference**: design §2.5, §5.1 (sequence diagram), §7 (risk mitigation: orders slice >400 LOC)
  - **Verification**: `wc -l services/orders.py` ≤ 160

- [x] **4.2** Create `services/payments.py` with public functions from design §2.6: `create_preference`, `handle_webhook`. Include `_validate_signature`, `_map_payment_status_to_order`. 📏 ~50 LOC
  - **Reference**: design §2.6, §5.4 (sequence diagram)
  - **Verification**: `python -c "from services.payments import create_preference, handle_webhook; print('OK')"`

- [x] **4.3** Create `services/shipping.py` with `get_prices` from design §2.7. Include `_default_prices` helper. 📏 ~30 LOC
  - **Reference**: design §2.7
  - **Verification**: `python -c "from services.shipping import get_prices; print('OK')"`

- [x] **4.4** Extend `services/exceptions.py` with remaining types from design §4: `ConcurrentStockUpdateError`, `InvalidStateTransitionError`, `ConflictError`, `DuplicateProductNameError`, `ForbiddenError`, `ShippingZoneError`, `ShippingZoneInvalidError`, `ShippingZoneDisabledError`, `EmptyCartError`. 📏 ~50 LOC
  - **Reference**: design §4 (class tree), §6 Slice 4
  - **Verification**: `python -c "from services.exceptions import ConcurrentStockUpdateError, EmptyCartError, ForbiddenError; print('OK')"`

- [x] **4.5** Refactor `routers/orders.py` to call services. All 6 endpoints → thin. Single shared `try/except` block per endpoint (parent-class catches where status_code matches). Preserve `$gte` guard + rollback via service. Remove all `get_collection` calls. 📏 ~200 removed, ~80 added
  - **Reference**: design §4 (worked try/except block), §5.1 (sequence diagram), §7 (translation byte-identity)
  - **Verification**: `rg "get_collection\(" routers/orders.py` returns zero

- [x] **4.6** Refactor `routers/payments.py` to call `services.payments.create_preference` and `services.payments.handle_webhook`. Remove collection deps. 📏 ~30 LOC change
  - **Reference**: design §2.6
  - **Verification**: `rg "get_collection\(" routers/payments.py` returns zero

- [x] **4.7** Refactor `routers/combos.py` admin endpoints to call `services.combos.create`, `update`, `delete`, `get_all_admin`. Refactor `routers/products.py` admin endpoints to call `services.products.create_admin`, `update_admin`, `delete_admin`, `toggle_active`. 📏 ~50 LOC change
  - **Reference**: design §2.4, §2.8 (admin functions)
  - **Verification**: `rg "get_collection\(" routers/combos.py routers/products.py` returns zero

- [x] **4.8** Update fixtures in `tests/test_orders_stock.py` and `tests/test_admin_stats.py` for `dependency_overrides` on `services.orders.*`, `services.payments.*`, `services.shipping.*`. **CRITICAL: per spec Requirement 5, assertion changes are NOT allowed; fixture overrides only.** 📏 ~30 LOC
  - **Reference**: spec Requirement: Test Suite Preservation (Scenario: Fixture changes do not alter test assertions)
  - **Verification**: `git diff tests/test_orders_stock.py tests/test_admin_stats.py | rg "assert"` returns zero

- [x] **4.9** Run full test suite: `pytest -v`. All 12 test files must pass. 📏 0 LOC
  - **Verification**: `pytest` exits 0

- [x] **4.10** Run MANUAL_SMOKE for all 6 endpoints: `POST /orders`, `GET /orders/me`, `GET /orders/{id}`, `POST /orders/{id}/select-payment-method`, `PUT /orders/admin/{id}/status`, `POST /payments/webhook` — byte-identical. Update `apply-progress.md` with final status (change complete pending verify). 📏 0 LOC
  - **Verification**: `curl` responses match golden files

---

## Phase 5: Verification (not a PR — orchestrator runs `sdd-verify`)

**Scope**: Full change verification
**Risk level**: N/A (orchestrator-side)

- [x] **5.1** Run full test suite end-to-end: `pytest -v --tb=short`. All 12 test files must pass with exit code 0. 📏 0 LOC
  - **Verification**: `pytest` exits 0

- [x] **5.2** Run MANUAL_SMOKE against all 6 listed endpoints from Phase 4. Compare each response body byte-for-byte with pre-refactor golden files. 📏 0 LOC
  - **Reference**: spec Requirement: API 1:1 Preservation (6 scenarios)
  - **Verification**: `diff` between golden and actual responses shows zero differences

- [x] **5.3** Confirm structural targets: `wc -l routers/*.py` totals ~2000 LOC (down from ~4000). `ls services/` shows 9 modules (`__init__.py`, `exceptions.py`, `inventory.py`, `pricing.py`, `cart.py`, `combos.py`, `orders.py`, `payments.py`, `shipping.py`, `products.py`). `rg "get_collection\(" routers/` returns zero across all extracted routers. 📏 0 LOC
  - **Reference**: spec Requirement: Service Module Shape, Requirement: Router → Service Translation Contract
  - **Verification**: commands above return expected counts

- [x] **5.4** Generate `openspec/changes/service-layer/verify-report.md` with: test suite result, MANUAL_SMOKE results, structural verification results, any deviations called out. 📏 ~50 LOC
  - **Verification**: file exists and documents all verification steps
