# Audit Logging & Idempotency Keys

## Capability: audit-logging

JSON audit trail for security events across auth, admin, payments, orders, and inventory.

### Requirements

| ID | Requirement |
|----|-------------|
| R1 | `AuditEvent` enum MUST add 12 values: `PASSWORD_RESET_REQUESTED`, `PASSWORD_RESET_COMPLETED`, `ADMIN_ROLE_CHANGED`, `ADMIN_USER_DELETED`, `ADMIN_PRODUCT_CREATED`, `ADMIN_PRODUCT_UPDATED`, `PAYMENT_FAILED`, `STOCK_DECREMENTED`, `STOCK_RESTORED`, `SIGNATURE_INVALID`, `MP_PREFERENCE_CREATED`, `ORDER_CANCELLED`. |
| R2 | Two helpers: `log_audit(event, request: Request | None, details: dict)` for routers; `log_audit_ctx(event, *, client_ip, method, path, details)` for services. Both emit identical JSON via the `audit` logger. |
| R3 | `AuditContext` dataclass carries `client_ip`, `method`, `path` from router to service layer. |
| R4 | Routers call `log_audit` at: auth (5 pts: login ✓/✗, register, forgot password, reset password); admin (1 pt: role change); products (2 pts: product create/update); payments (1 pt: webhook). |
| R5 | Services call `log_audit_ctx` at: payments (3: payment failed, MP pref created, bad signature); orders (3: created, cancelled, status changed); inventory (2: stock decremented/restored). |
| R6 | Hot-path audit (stock decrement) MUST use `asyncio.create_task` — fire-and-forget, never blocks response. |
| R7 | Every entry is JSON: `event`, `client_ip`, `method`, `path`, `timestamp` (ISO 8601 UTC), `details`. |

### Scenarios

**S1.1 — Router emits correct JSON**
- GIVEN `POST /auth/login` succeeds
- WHEN `log_audit(USER_LOGIN_SUCCESS, request, {"user_id": "x"})` is called
- THEN `audit` logger emits JSON with all 6 keys populated correctly.

**S1.2 — Service audit via AuditContext**
- GIVEN service receives `AuditContext(client_ip="1.2.3.4", method="POST", path="/orders")`
- WHEN `log_audit_ctx` is called
- THEN output structure matches router-emitted JSON exactly.

**S1.3 — request=None safe**
- GIVEN `log_audit(event, None, details)`
- THEN `client_ip`/`method`/`path` default to `"N/A"`; no exception.

**S1.4 — Fire-and-forget latency**
- GIVEN stock decrement on `POST /orders`
- WHEN audit is wrapped in `create_task`
- THEN p95 ≤ 2ms; response returns without awaiting audit.

**S1.5 — Log forging prevention**
- GIVEN `details` contains newlines or JSON special chars
- WHEN serialized via `json.dumps`
- THEN output is a single valid JSON line; no injection.

---

## Capability: idempotency-keys

Redis-backed idempotency for `POST /orders` and `POST /payments/create-preference`.

### Requirements

| ID | Requirement |
|----|-------------|
| R1 | Extract `Idempotency-Key` header; validate as UUID-4. Invalid → 400. |
| R2 | First sight: store response via Redis `SET NX` with TTL 86400s. |
| R3 | Duplicate key (hit): return cached response (status code preserved) without re-executing handler. |
| R4 | Missing header: generate server-side fallback key (hash of user_id + payload). |
| R5 | Redis unreachable: log WARNING, proceed without idempotency (fail-open). |
| R6 | Redis keys namespaced as `{user_id}:{header_value}` — per-user isolation. |

### Scenarios

**S2.1 — First request caches response**
- GIVEN `POST /orders` with `Idempotency-Key: <uuid4>`
- WHEN no key exists in Redis
- THEN order created, response cached (TTL 86400), original status code preserved.

**S2.2 — Duplicate replays cached response**
- GIVEN same key was used within 24h
- WHEN request is repeated
- THEN cached JSON returned; no second order/stock decrement.

**S2.3 — Invalid UUID rejected**
- GIVEN `Idempotency-Key: not-a-uuid`
- WHEN router validates
- THEN 400 returned before business logic.

**S2.4 — Missing header → fallback**
- GIVEN no `Idempotency-Key` header
- WHEN request arrives
- THEN server derives fallback key; request proceeds normally.

**S2.5 — Redis down → fail-open**
- GIVEN Redis unreachable
- WHEN `POST /orders` called
- THEN WARNING logged; order created without idempotency.

**S2.6 — Cross-user isolation**
- GIVEN users A and B send same UUID
- WHEN keys are `userA:<uuid>` vs `userB:<uuid>`
- THEN independent responses; no cross-user replay.

### Invariants

1. Audit writes MUST NOT raise unhandled exceptions to callers.
2. Idempotency MUST NOT block requests when Redis is down.
3. No event logged twice for the same logical operation.
4. Non-UUID `Idempotency-Key` rejected before any business logic.
