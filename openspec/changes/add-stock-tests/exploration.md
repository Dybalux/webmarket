## Exploration: add-stock-tests

### Current State
- The webmarket FastAPI app has a stock control system spread across multiple routers with NO test infrastructure whatsoever
- `requirements.txt` has ZERO test dependencies (no pytest, pytest-asyncio, httpx, mongomock, anyio beyond the runtime dep)
- `requirements-prod.txt` only has gunicorn
- No `conftest.py`, no `pytest.ini`, no `pyproject.toml`, no `tox.ini` exist in the project
- `openspec/config.yaml` already records: `testing.strict_tdd: false`, `runner: null`, all layers `false`
- The only "tests" that exist are `scripts/test_email.py` and `scripts/test_webhook.py` — manual smoke scripts, not pytest
- `database.py` uses a module-level singleton `db = Database()` with `client` and `db` attributes — every test must reset this singleton via monkeypatching

### Stock Code Map (every touchpoint)
1. **`stock_helpers.py` (DEAD CODE)**
   - `validate_and_reserve_stock(session, products_collection, items)` — pure async function, takes Motor session + collection
   - `update_stock_atomic(session, products_collection, items)` — pure async, uses `$inc` with `$gte` guard
   - `rollback_stock(session, products_collection, items)` — pure async, `$inc` positive
   - All three take `AsyncIOMotorClientSession` → require a fake/mocked session object
   - Line 11 of `orders.py` has `# from stock_helpers import ...  # Descomenta cuando uses MongoDB M10+` — these helpers exist for the future M10+ transactional code path but the transactional code itself is also commented out (orders.py lines 396-485)

2. **`routers/orders.py` — stock-critical code paths**
   - `process_combo_item()` (lines 29-91) — fetches combo, expands items, validates per-product stock, returns `products_to_decrement` list
   - `create_order()` (lines 177-394) — checks stock at line 265, then decrements at line 362-365 with NO atomicity (the race condition)
   - `update_order_status()` (lines 572-626) — repositions stock on CANCELLED/REFUNDED, lines 596-615. BUG: condition check at line 596 has an indentation issue — the `for item` loop is OUTSIDE the `if new_status in [...]` block, so stock is reposed for ANY status transition

3. **`routers/inventory.py` — stock endpoints**
   - `check_and_create_alert()` (lines 25-48) — threshold check at 10 units, dedup by exact `message` string (fragile: any stock change to a different number creates a new alert)
   - `update_product_stock` PUT `/{product_id}/stock` — admin only, sets absolute stock, calls `check_and_create_alert`
   - `add_to_product_stock` PUT `/{product_id}/stock/add` — admin only, `$inc` positive
   - `get_inventory_alerts` GET `/alerts` — admin only, sorted by timestamp desc
   - Constant: `LOW_STOCK_THRESHOLD = 10` (hardcoded, not configurable)

4. **`routers/cart.py` — stock validation in cart flows**
   - `add_to_cart` (line 167) — validates stock BEFORE adding, handles products + combos
   - `update_cart_item_quantity` (line 259) — validates stock on quantity update
   - `validate_cart_stock` GET `/validate-stock` (line 430) — read-only validation across all items, returns per-item availability + `all_available` flag

5. **`routers/products.py` — stock in catalog**
   - `read_products` GET `/` (line 55) — filters `stock > 0` by default, `include_out_of_stock=True` for admins
   - No stock mutation in this router (creation/update are admin-only but go through `update_product`)

6. **`routers/admin.py` — stock in stats**
   - `get_admin_stats` GET `/stats` (line 28) — `low_stock_products = count_documents({"stock": {"$lt": 10}})` — DUPLICATED threshold constant, not using `LOW_STOCK_THRESHOLD` from inventory

7. **`models.py`**
   - `Product.stock: int = Field(..., ge=0)` — Pydantic validates `stock >= 0` at the model level
   - `InventoryAlert` model — `product_id: str` (not ObjectId), `current_stock`, `threshold`, `message`, `timestamp`

### Bugs and Risks Found
1. **CRITICAL: Race condition in `create_order`** (orders.py line 265 vs 362-365) — stock check and decrement are TWO separate non-atomic operations. Two concurrent orders for the last 5 units will both pass validation and both decrement → negative stock.
2. **CRITICAL: Indentation bug in `update_order_status`** (orders.py lines 596-615) — the `for item in current_order["items"]:` loop is NOT indented under the `if new_status in [CANCELLED, REFUNDED]` check. Stock gets incremented on EVERY status change, not just cancel/refund. This double-reposes stock if status is updated multiple times.
3. **Dead code**: `stock_helpers.py` (146 lines) — imported nowhere, transactional code path in orders.py (lines 396-485) is also commented out
4. **Duplicated threshold constant**: `LOW_STOCK_THRESHOLD = 10` in inventory.py AND `{"stock": {"$lt": 10}}` hardcoded in admin.py
5. **Fragile alert dedup**: `existing_alert = alerts_collection.find_one({"product_id": ..., "message": alert_message})` — message includes current stock number, so any stock change creates a new alert. Spammable.
6. **No stock check after decrement** in non-transactional code path — decrements blindly with `{"_id": p["id"]}` filter, no `{"$gte": quantity}` guard like `update_stock_atomic` uses
7. **Combo stock expansion uses `process_combo_item` and re-validates in `create_order`** — duplicate code paths
8. **Maintenance middleware** in main.py calls `get_database()` on EVERY request — coupling that affects test setup

### Testability Analysis

| Layer | Functions | Strategy |
|-------|-----------|----------|
| Pure unit (no DB) | None — all stock code touches Mongo | — |
| Unit (mocked Motor) | `check_and_create_alert`, `process_combo_item`, `stock_helpers.*` (3 functions) | Use `unittest.mock.AsyncMock` with fake `AsyncIOMotorClientSession` |
| Endpoint integration | All stock endpoints across orders/inventory/cart | FastAPI `TestClient` (httpx-based) + `mongomock-motor` |
| Property-based | Threshold logic, alert dedup | Hypothesis (optional) |

`stock_helpers` is the easiest to test in isolation — only depends on (session, collection) and a list of dicts. Each is a single responsibility: validate, decrement, rollback. They could be tested in <50 lines of pytest.

The router code is much harder — every endpoint wires 4-6 FastAPI dependencies (`get_database`, `get_collection`, `get_current_active_user_id`, `get_current_verified_user`, `get_current_admin_user`). Tests must override these with `app.dependency_overrides`.

### Dependency Gap
**Missing for ANY test**:
- `pytest` (test runner)
- `pytest-asyncio` (Motor is async — `asyncio_mode = "auto"` recommended)
- `httpx` (FastAPI TestClient dep)
- `mongomock-motor` (in-memory async MongoDB that emulates Motor's API) — `mongomock` alone is sync only

**Optional but valuable**:
- `pytest-cov` (coverage)
- `freezegun` (for timestamp-based alert dedup tests)
- `pytest-mock` (cleaner AsyncMock patterns)
- `ruff` (linter — already config is `false`, low priority)

No transitive conflict expected: FastAPI 0.116 already pulls in `anyio 4.10`, `starlette 0.47`, `h11`. `httpx` is needed by FastAPI's `TestClient` and is missing from requirements — would need to add it.

### Approaches Compared

| Approach | Pros | Cons | Effort |
|----------|------|------|--------|
| **A. Pure unit tests with AsyncMock** | Zero infra cost, fast, isolates logic, perfect for `stock_helpers` | Doesn't catch MongoDB query bugs, doesn't test wire-up | Low |
| **B. Integration tests with mongomock-motor** | Tests real Motor query semantics, can verify `$gte` guards and `find_one` mocks work | mongomock-motor doesn't support transactions (M10+ helper untestable this way), sessions still need mocking | Medium |
| **C. Endpoint tests with TestClient + mongomock-motor** | Closest to production, exercises auth deps via `app.dependency_overrides`, catches router bugs | Heaviest setup, must reset `db` singleton in `database.py` between tests, must disable MaintenanceModeMiddleware | High |
| **D. Contract tests for `stock_helpers`** | Documents the helper API surface, enables safe refactor | Not a testing strategy on its own — supplements A or B | Low |

### Recommendation
**Layered approach (B + A combined, in that order of value)**:
1. **Phase 1 — Foundation**: Add `pytest`, `pytest-asyncio`, `httpx`, `mongomock-motor` to a new `requirements-dev.txt`. Add `conftest.py` with fixtures that (a) reset the `db` singleton, (b) override `get_database`/`get_collection` deps, (c) override auth deps, (d) provide a `client` fixture using `TestClient`.
2. **Phase 2 — `stock_helpers` unit tests** (Approach A + D): high value, low cost. Covers the atomic decrement guard (`$gte` + `modified_count == 0` → 409), rollback, validation. ~10 tests.
3. **Phase 3 — Router integration tests** (Approach B+C): `test_create_order_race`, `test_cancel_order_reposes_stock`, `test_low_stock_alert_threshold`, `test_validate_cart_stock_mixed`, `test_admin_stats_low_stock_count`. ~15 tests, highest business value.
4. **Phase 4 — Optional**: hypothesis property tests for the threshold logic.

Skip contract-only tests (D alone) — not valuable without the implementation tests.

### Risks
- **mongomock-motor does NOT support transactions** → `stock_helpers` cannot be tested end-to-end via the transactional `validate_and_reserve_stock + update_stock_atomic` flow. Either skip these, or test the helpers WITHOUT a session (they'd fail with `session=session` because mongomock-motor ignores it gracefully but won't enforce atomicity).
- **MaintenanceModeMiddleware** in main.py calls `get_database()` on every request → TestClient must either mock this or it will try to connect to real Mongo. Need to disable middleware in test fixture.
- **Module-level `db = Database()` singleton** in database.py makes test isolation tricky — must use `monkeypatch.setattr(database, "db", mock_db)` and reset between tests.
- **FastAPI lifespan** tries to connect to MongoDB AND Redis on startup → TestClient app must use a test app that bypasses the real lifespan (use a fixture that builds a minimal app with `routers=` only, or use `httpx.AsyncClient` directly with the app).
- **Pydantic `Product.stock: int = Field(..., ge=0)`** means malformed test data (negative stock) will be rejected at the model layer, not the DB — tests must use valid Pydantic models.
- **`audit_logger.py` and `email_service.py`** are imported by routers — tests need to mock these or they'll try to send real emails/log to real audit collection.
- **Test file count could exceed 400-line PR budget** if all phases are bundled. Recommend Phase 1+2 as PR #1 (foundation + helpers, ~200 lines), Phase 3 as PR #2 (router integration, ~500 lines — chained PR risk).

### Ready for Proposal
**Yes** — exploration complete. The orchestrator should now launch `sdd-propose` for `add-stock-tests` with:
- Scope: add test infrastructure (dev deps + conftest) and stock-focused tests across `stock_helpers` + the 3 stock-critical routers
- Phased delivery: foundation+helper unit tests first, then router integration tests
- Explicit decision point: do we ALSO fix the indentation bug + race condition discovered, or ONLY add tests that document the bugs? Recommendation: tests only in this change, fixes in a follow-up `fix-stock-bugs` change (clearer PR review, smaller blast radius).

### Affected Files (summary)
- `requirements.txt` — add dev deps split
- `requirements-dev.txt` — NEW
- `conftest.py` — NEW
- `pytest.ini` or `pyproject.toml` — NEW
- `tests/test_stock_helpers.py` — NEW
- `tests/test_orders_stock.py` — NEW
- `tests/test_inventory.py` — NEW
- `tests/test_cart_stock.py` — NEW
- `tests/test_admin_stats.py` — NEW
- No source files modified (test-only change)
