# Proposal: Add Stock Control Tests

## Intent

Stock control spans 7 touchpoints across 5 files (`stock_helpers.py`, `routers/orders.py`, `routers/inventory.py`, `routers/cart.py`, `routers/products.py`) with **zero coverage and no test infrastructure**. Exploration found two production bugs (race condition in `create_order`, indentation bug in `update_order_status`) that can't be safely refactored without a regression net.

This change adds test infrastructure + stock-focused tests across all three layers. **Tests only — no production code changes.** Bug fixes are deferred to `fix-stock-bugs` for cleaner review.

## Scope

### In Scope
- `requirements-dev.txt` (new): pytest, pytest-asyncio, httpx, mongomock-motor, pytest-cov, freezegun, pytest-mock
- `pytest.ini` (new): asyncio_mode=auto, testpaths=tests
- `conftest.py` (new): `reset_db_singleton`, `mock_db`, `override_db_deps`, `auth_user_dep`, `auth_admin_dep`, `client` (TestClient, middleware + lifespan bypass)
- `tests/` (new): `test_stock_helpers.py`, `test_orders_stock.py`, `test_inventory.py`, `test_cart_stock.py`, `test_admin_stats.py`
- `openspec/config.yaml` (modified): `testing.runner=pytest`, enable layers
- `requirements.txt` (modified): optional `-r requirements-dev.txt` reference

### Out of Scope
- Race condition + indentation bug fixes → `fix-stock-bugs`
- Activating `stock_helpers.py` transactional path (needs M10+)
- Removing `stock_helpers.py` dead code, deduping `LOW_STOCK_THRESHOLD`, reworking alert dedup
- CI / coverage gates — separate changes

## Capabilities

### New Capabilities
- `testing-infrastructure`: pytest setup, dev deps, shared fixtures (DB singleton reset, dep overrides, TestClient, auth mocks). → `openspec/specs/testing-infrastructure/spec.md`
- `stock-control-tests`: behavioral test contract — `stock_helpers` (validate/reserve/rollback), `check_and_create_alert` (threshold + dedup), `create_order` flow, `update_order_status` reposes, cart validation, admin low-stock count. → `openspec/specs/stock-control-tests/spec.md`

### Modified Capabilities
- **None** — tests document existing behavior. Requirement changes from bug fixes go in `fix-stock-bugs`.

## Approach

**Three chained PRs** to stay under 400-line review budget:

| PR | Scope | ~Lines | Risk |
|----|-------|--------|------|
| #1 | Foundation: deps + conftest + pytest.ini + `test_stock_helpers.py` (10 tests) | ~250 | Low |
| #2 | Integration: `test_inventory.py` + `test_admin_stats.py` (12 tests) | ~350 | Med |
| #3 | Endpoints: `test_orders_stock.py` + `test_cart_stock.py` (15 tests) | ~500 | High — sdd-tasks will forecast; split further if needed |

PR #1 is foundation — nothing else merges without it.

**Test app pattern** (avoids `MaintenanceModeMiddleware` + `db` singleton pitfalls): minimal `FastAPI()` in conftest mounting only routers under test; `app.dependency_overrides` swap `get_database`/`get_collection`/`get_current_*_user`; `mongomock-motor` `AsyncMongoMockClient` per test with reset; `monkeypatch.setattr(database, "db", mock_db)` to break singleton; no `lifespan` (skip Mongo/Redis startup).

**stock_helpers** are pure async — test with `AsyncMock` session + real `mongomock-motor` collection. mongomock-motor has no transactions → atomicity verified via `$gte` filter + `modified_count`, not multi-doc commit semantics. Endpoint tests use FastAPI `TestClient` (httpx, sync) with auth deps overridden.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `requirements.txt` | Modified | Optional `-r requirements-dev.txt` |
| `requirements-dev.txt` | New | Dev deps |
| `pytest.ini` | New | Pytest config |
| `conftest.py` | New | Shared fixtures |
| `tests/` | New | 5 test files |
| `openspec/config.yaml` | Modified | `testing.*` updated |
| `routers/`, `stock_helpers.py`, `models.py`, `database.py` | **Not modified** | Test-only |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `mongomock-motor` diverges from real Motor on `$gte`/`$inc` | Med | Cover `$gte` + `modified_count` explicitly; docstrings mark "mongomock contract" |
| Module-level `db` singleton leaks between tests | High | Reset fixture + per-test `monkeypatch` |
| MaintenanceModeMiddleware hits real Mongo on startup | High | Minimal app in conftest, never import `main.py` |
| PR #3 still exceeds 400-line budget | Med | sdd-tasks will forecast; split further if high |
| Tests document buggy behavior and lock it in | Med | `pytest.mark.xfail` on bug-exercising tests + TODO to `fix-stock-bugs` |
| `audit_logger.py` / `email_service.py` side effects | Med | Mock both in conftest |
| pytest-asyncio + motor fixture loop scope mismatch | Low | Pin `event_loop` to function scope |

## Rollback Plan

Test-only change. Revert the PRs / remove `tests/`, `requirements-dev.txt`, `conftest.py`, `pytest.ini`. `requirements-prod.txt` unchanged. No DB migrations, env vars, or feature flags. Each PR reverts independently.

## Dependencies

- FastAPI 0.116 in `requirements.txt` (pulls starlette, anyio, h11)
- `httpx` not transitive from FastAPI — add explicitly for TestClient
- `mongomock-motor` is the async fork; pure `mongomock` is sync-only
- Python 3.13 + pytest-asyncio ≥ 0.23
- No MongoDB/Redis required locally

## Success Criteria

- [ ] `pytest` runs from project root, exits 0
- [ ] `pip install -r requirements-dev.txt` works in fresh venv
- [ ] All 3 `stock_helpers.py` functions have unit tests
- [ ] Router integration tests cover: alert dedup, `create_order` flow, `update_order_status` reposes, cart validation, admin low-stock count
- [ ] Suite runs < 10s total
- [ ] No source file in `routers/`, `stock_helpers.py`, `models.py`, `database.py` modified (`git diff --stat` clean)
- [ ] `openspec/config.yaml` reflects new testing setup
- [ ] Two known bugs marked `xfail` with TODO links to `fix-stock-bugs`
- [ ] Foundation PR (#1) merges first
