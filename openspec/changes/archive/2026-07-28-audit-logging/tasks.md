# Tasks: Audit Logging & Idempotency

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~680 total (PR-1 ~380, PR-2 ~300) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR-1 (audit) → dev, PR-2 (idempotency) → dev |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Audit logging core + wiring + tests | PR-1 | `pytest tests/unit/test_audit_logger.py tests/integration/test_audit_wiring.py -v` | AsyncMock + caplog | Revert audit_logger.py + router/service wiring |
| 2 | Idempotency core + wiring + tests | PR-2 | `pytest tests/unit/test_idempotency.py tests/integration/test_idempotency_replay.py -v` | FakeRedis + test_client | Revert utils/idempotency.py + router wiring |

## PR-1: Audit Logging

### Phase 1: Core (audit_logger.py refactor)

- [x] 1.1 Add 12 `AuditEvent` enum values to `audit_logger.py`
- [x] 1.2 Add frozen `AuditContext` dataclass with `from_request()` classmethod
- [x] 1.3 Refactor `log_audit` to async, accept `Request | None`, delegate to `_emit`
- [x] 1.4 Add `log_audit_ctx` async helper for service layer
- [x] 1.5 Implement `_emit` with try/except (never raises), JSON serialization, fallback warning

### Phase 2: Router wiring

- [x] 2.1 Wire `log_audit` into `routers/auth.py` (login ✓/✗, register, reset request/complete)
- [x] 2.2 Wire `log_audit` into `routers/admin.py` (role change); product create/update wired in `routers/products.py`. Note: `ADMIN_USER_DELETED` enum added but no endpoint exists — wiring deferred (design open question).
- [x] 2.3 Wire `log_audit` into `routers/payments.py` (webhook)
- [x] 2.4 Add `Request` parameter to affected router functions, build `AuditContext`

### Phase 3: Service wiring

- [x] 3.1 Add optional `audit_ctx` kwarg to `services/payments.py`; call `log_audit_ctx` for payment failed, MP preference created, signature invalid
- [x] 3.2 Add optional `audit_ctx` kwarg to `services/orders.py`; call `log_audit_ctx` for order created, cancelled, status changed, stock restored
- [x] 3.3 Add `asyncio.create_task` fire-and-forget for `STOCK_DECREMENTED` in `services/orders_helpers.py`
- [x] 3.4 Add optional `audit_ctx` kwarg to `services/inventory.py`; call `log_audit_ctx` with fire-and-forget for stock decremented/restored

### Phase 4: Tests (unit + integration)

- [x] 4.1 Create `tests/unit/test_audit_logger.py`: JSON shape, request=None, ctx parity, forging prevention
- [x] 4.2 Create `tests/integration/test_audit_wiring.py`: AsyncMock asserts for all call points across routers/services
- [x] 4.3 Update `tests/conftest.py` silence fixture to also patch `log_audit_ctx`
- [x] 4.4 Verify fire-and-forget latency (S1.4) via timing assertion in integration test

## PR-2: Idempotency

### Phase 1: Core (utils/idempotency.py)

- [x] 5.1 Create `utils/idempotency.py` with `validate_key` (UUID-4 validation, 400 on invalid)
- [x] 5.2 Implement `get_or_set` (Redis SET NX, IN_FLIGHT state, cached JSON replay)
- [x] 5.3 Implement `fallback_key` (SHA-256 of user_id + endpoint + payload)
- [x] 5.4 Add fail-open logic: catch RedisError → WARNING → proceed without idempotency

### Phase 2: Router wiring

- [x] 6.1 Wire idempotency into `routers/orders.py`: extract header, validate UUID, call `get_or_set`, cache response
- [x] 6.2 Wire idempotency into `routers/payments.py`: extract header, validate UUID, call `get_or_set`, cache response
- [x] 6.3 Handle missing header with `fallback_key`, handle Redis down with fail-open

### Phase 3: Tests (unit + integration)

- [x] 7.1 Create `tests/unit/test_idempotency.py`: UUID validation, fallback key, fail-open, cross-user isolation
- [x] 7.2 Create `tests/integration/test_idempotency_replay.py`: duplicate `POST /orders` → one order, one stock decrement
- [x] 7.3 Update `tests/conftest.py` with `FakeRedis.set(nx=, ex=, keepttl=)` support
- [x] 7.4 Verify 409 on duplicate while IN_FLIGHT, verify 200 cached response on replay

## Phase 5: Cleanup

- [x] 8.1 Remove dead code from original `log_audit` if any remains
- [x] 8.2 Ensure all new enum values are documented in docstrings
- [x] 8.3 Run full test suite `pytest tests/ -v --tb=short` to verify no regressions