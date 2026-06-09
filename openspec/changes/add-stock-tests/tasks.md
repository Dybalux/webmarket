# Tasks: Add Stock Control Tests

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1100 total (PR1 ~250, PR2 ~350, PR3 ~500) |
| 400-line budget risk | **High** (PR3 alone ≈ 500) |
| Chained PRs recommended | **Yes** (already split by proposal into 3 PRs) |
| Suggested split | PR #1 → PR #2 → PR #3 (foundation first) |
| Delivery strategy | ask-always |
| Chain strategy | feature-branch-chain (PR #1 → tracker branch; child PRs target previous PR) |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Per-PR Budget

| PR | Scope | Est. changed lines | 400-line risk | Status |
|----|-------|-------------------:|---------------|--------|
| #1 | Foundation: deps + conftest + pytest.ini + `test_stock_helpers.py` | ~250 | Low | OK as single PR |
| #2 | Integration: `test_inventory.py` + `test_admin_stats.py` | ~350 | Low | OK as single PR |
| #3 | Endpoints: `test_orders_stock.py` + `test_cart_stock.py` | ~500 | **High** | **Split further or request `size:exception`** |

PR #3 forecast exceeds 400 lines. Recommended resolution: split PR #3 into PR #3a (orders) + PR #3b (cart) OR request `size:exception`. Flag to user before apply.

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Test infra + unit tests for stock_helpers + models | PR 1 | base = main. Merges first; blocks all others. |
| 2 | Integration tests for inventory router + admin stats | PR 2 | base = main. Depends on PR 1. |
| 3a | Endpoint tests for orders (create, cancel, refund) | PR 3a | base = main. Depends on PR 1, PR 2. |
| 3b | Endpoint tests for cart validation + products filter | PR 3b | base = main. Depends on PR 1. Independent of PR 3a. |

---

## Phase 1: PR #1 — Test Infrastructure + Unit Tests (Foundation)

- [x] **T1.1** Create `requirements-dev.txt` with pinned: `pytest`, `pytest-asyncio`, `httpx`, `mongomock-motor`, `pytest-cov`, `freezegun`, `pytest-mock`. Modify `requirements.txt` to add `-r requirements-dev.txt`. Verify: `pip install -r requirements-dev.txt` succeeds and `pytest --version` works. (~15 lines)
- [x] **T1.2** Create `pytest.ini` with `asyncio_mode=auto`, `testpaths=tests`, `pythonpath=.[tests]`, markers `unit|integration|endpoint`, and `[pytest-cov]` source set for `routers,stock_helpers,models,database,pricing_helpers`. Verify: `pytest --collect-only` succeeds. (~25 lines)
- [x] **T1.3** Create `tests/__init__.py` (empty) and `tests/conftest.py` exporting fixtures: `mock_db` (fresh `AsyncMongoMockClient` per test, function scope), `reset_db_singleton` (monkeypatches `database.db` + clears module caches), `override_db_deps` (overrides `get_database`/`get_collection` via `app.dependency_overrides`), `auth_user_dep` / `auth_admin_dep` (overrides for the three auth deps), `client` (builds minimal `FastAPI()` with only `MaintenanceModeMiddleware` excluded, no `lifespan`, `TestClient` bound to it). Also mock `audit_logger.log` and `email_service.send_email` via `monkeypatch.setattr`. Verify: `pytest --fixtures` lists all six. (~120 lines)
- [x] **T1.4** In `tests/test_stock_helpers.py` write unit tests for `Product.stock` validation (negative rejected via `ValidationError`, zero accepted), `InventoryAlert` (constructs + serializes to JSON), `OrderItem` and `CartItem` (quantity=0 rejected, positive accepted). Use markers `@pytest.mark.unit`. Verify: `pytest tests/test_stock_helpers.py -m unit` passes. (~50 lines)
- [x] **T1.5** In same file add unit tests for `validate_and_reserve_stock` with `AsyncMock` session + real `mongomock-motor` collection: valid+sufficient (no write), invalid product ID (raises "product not found"), insufficient stock (raises with product+quantity), multi-item batch (processes all). Add docstring noting `mongomock-motor` does not support transactions. Verify: `pytest tests/test_stock_helpers.py::test_validate_and_reserve_stock -v` passes. (~70 lines)
- [x] **T1.6** In same file add unit tests for `update_stock_atomic` (decrement with `$gte` guard: success on stock=10→7, race detection on stock=2 with quantity=5 returning `modified_count=0`, stock unchanged) and `rollback_stock` (stock=7 + quantity=3 → stock=10). Verify: `pytest tests/test_stock_helpers.py -k atomic_or_rollback` passes. (~55 lines)
- [x] **T1.7** In `tests/test_inventory.py` (stub section) add unit-level test for `check_and_create_alert` logic: alert created at threshold (stock=10), no alert above threshold (stock=15), dedup when `(product_id, message)` already exists. Verify: `pytest tests/test_inventory.py -k alert -v` passes. (~50 lines)
- [x] **T1.8** Modify `openspec/config.yaml` `testing:` block: set `runner: pytest`, `framework: pytest`, `layers.{unit,integration,e2e}: true`. Verify: `python -c "import yaml; print(yaml.safe_load(open('openspec/config.yaml'))['testing'])"` shows the updated runner. (~10 lines)

**PR #1 total: ~395 lines (deps+config ~50, conftest ~120, pytest.ini ~25, tests ~200)**

---

## Phase 2: PR #2 — Integration Tests (mongomock-motor)

Depends on: PR #1 merged.

- [ ] **T2.1** In `tests/test_inventory.py` add integration test for stock decrement on order: seed product with stock=5, seed cart with one of that product, call `POST /orders` (use minimal app mounting only orders router), assert product stock=4 and order response. Mark `@pytest.mark.xfail(strict=False, reason="Race condition in create_order; see fix-stock-bugs")`. Verify: `pytest tests/test_inventory.py::test_order_decrements_stock -v` reports `xfail`. (~40 lines)
- [ ] **T2.2** In same file add multi-item decrement test: three products stock=5, cart with one of each, `POST /orders` → all three stocks=4, order has 3 line items. Same `xfail` marker. Verify: `pytest tests/test_inventory.py -k multi_item` reports `xfail`. (~45 lines)
- [ ] **T2.3** In same file add combo decrement test: combo = [productA, productB], each stock=5, order the combo → both component stocks=4, order records combo as one line. `xfail` marker. Verify: `pytest tests/test_inventory.py -k combo` reports `xfail`. (~45 lines)
- [ ] **T2.4** In same file add stock validation test: product stock=2, cart requests quantity=5, `POST /orders` → HTTP 409 with body identifying under-stocked product, stock unchanged. Verify: `pytest tests/test_inventory.py -k insufficient` passes. (~30 lines)
- [ ] **T2.5** In same file add low-stock alert on order test: seed product stock=12, place order reducing to 8, assert `InventoryAlert` doc exists with `current_stock=8, threshold=10`. Verify: `pytest tests/test_inventory.py -k low_stock_alert` passes. (~35 lines)
- [ ] **T2.6** In same file add alert dedup test: seed product stock=8 with existing alert (matching message), trigger second stock drop → no new alert inserted, collection count unchanged. Verify: `pytest tests/test_inventory.py -k alert_dedup` passes. (~30 lines)
- [ ] **T2.7** In `tests/test_inventory.py` (admin section) add product filter tests: `GET /products` excludes zero-stock by default, `GET /products?include_out_of_stock=true` (admin) includes them. Use `auth_user_dep` / `auth_admin_dep` overrides. Verify: `pytest tests/test_inventory.py -k products_filter` passes. (~50 lines)
- [ ] **T2.8** In `tests/test_admin_stats.py` add admin low-stock count test: seed N products with stock<threshold, call admin stats endpoint, assert count == N. Use `auth_admin_dep` override. Verify: `pytest tests/test_admin_stats.py -v` passes. (~40 lines)
- [ ] **T2.9** Add `pytest.mark.integration` to all tests in `test_inventory.py` and `test_admin_stats.py`. Verify: `pytest -m integration` runs all 8. (~5 lines)

**PR #2 total: ~320 lines**

---

## Phase 3: PR #3 — Endpoint Tests (FastAPI TestClient)

Depends on: PR #1 + PR #2 merged.

> **PR #3 budget warning**: ~500 lines > 400 budget. Recommend splitting into PR #3a (orders: T3.1–T3.4, ~280 lines) + PR #3b (cart + admin: T3.5–T3.7, ~200 lines) OR request `size:exception`. **Resolve before apply.**

- [ ] **T3.1** In `tests/test_orders_stock.py` add endpoint test for `PUT /inventory/{id}/stock`: admin sets stock=5 on product with stock=20 → product stock=5, low-stock alert created. Use `auth_admin_dep` override. Mark `@pytest.mark.endpoint`. Verify: `pytest tests/test_orders_stock.py -k set_stock` passes. (~40 lines)
- [ ] **T3.2** In same file add `PUT /inventory/{id}/stock/add` test: admin adds quantity=20 to product with stock=5 + existing alert → stock=25, no new alert. Verify: `pytest tests/test_orders_stock.py -k add_stock` passes. (~40 lines)
- [ ] **T3.3** In same file add `GET /inventory/alerts` test: seed 3 alerts with different timestamps, admin call → 200, first element is most recent. Add non-admin 403 test for `PUT /inventory/{id}/stock`. Verify: `pytest tests/test_orders_stock.py -k alerts` passes. (~50 lines)
- [ ] **T3.4** In same file add full `POST /orders` endpoint test (happy path with all stock helpers wired): seed products, build cart via fixture, call endpoint, assert response + stock changes. Mark `xfail` (race condition). Verify: `pytest tests/test_orders_stock.py -k full_order` reports `xfail`. (~50 lines)
- [ ] **T3.5** In `tests/test_orders_stock.py` add `PUT /orders/admin/{id}/status` cancel + refund tests: deliver order, then admin sets status=CANCELLED → each product stock incremented. Same for REFUNDED. Mark `xfail` (indentation bug). Verify: `pytest tests/test_orders_stock.py -k cancel_or_refund` reports `xfail`. (~60 lines)
- [ ] **T3.6** In `tests/test_cart_stock.py` add `GET /cart/validate-stock` tests: all items in stock → `all_available=true` + per-item `available=true`; one item insufficient → `all_available=false` + per-item `available=false` with available quantity. Use `auth_user_dep` override. Verify: `pytest tests/test_cart_stock.py -v` passes. (~70 lines)
- [ ] **T3.7** In same file add `GET /products` endpoint test complementing T2.7: call via TestClient with admin override, verify query param routing. Verify: `pytest tests/test_cart_stock.py -k products` passes. (~30 lines)
- [ ] **T3.8** Add `pytest.mark.endpoint` to all tests in `test_orders_stock.py` and `test_cart_stock.py`. Verify: `pytest -m endpoint` runs the full layer. (~5 lines)

**PR #3 total: ~345 lines (before marker overhead) — fits if split as 3a (T3.1–T3.4 + T3.5 cancel/refund: ~240) + 3b (T3.6–T3.7: ~100)**

---

## Phase 4: Cleanup & Verification

- [ ] **T4.1** Run full suite: `pytest` from project root. Assert exit 0 and total runtime < 10s.
- [ ] **T4.2** Run `git diff --stat` excluding `tests/`, `requirements-dev.txt`, `pytest.ini`, `conftest.py`, `openspec/config.yaml`. Assert zero changes in `routers/`, `stock_helpers.py`, `models.py`, `database.py` (production code untouched per proposal rollback plan).
- [ ] **T4.3** Run `pytest --cov=routers --cov=stock_helpers --cov=models --cov=database --cov=pricing_helpers --cov-report=term-missing` and capture the report. Note: coverage threshold is 0% for this change; document the baseline.
- [ ] **T4.4** Confirm all bug-exercising tests carry `@pytest.mark.xfail(strict=False, reason="Bug exercised; see fix-stock-bugs")` and that `pytest --strict-markers` passes.
