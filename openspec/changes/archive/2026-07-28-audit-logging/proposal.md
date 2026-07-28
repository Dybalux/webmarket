# Proposal: Audit Logging & Idempotency

## Intent

`audit_logger.log_audit` is dead code — defined but never called. ~12 security events go unlogged (failed password attempts, admin role changes, stock mutations, payment failures, signature failures, password resets). Violates OWASP A09; leaves F-014 unresolved. Order creation and `create_mp_preference` also accept no `Idempotency-Key` (F-022, OWASP A04) — a double-click duplicates orders, double-decrements stock, and creates multiple MP preferences. MP SDK does not pass the header natively, so enforcement is application-level via Redis. **PR #6 of 6** in the 2026-06-15 audit remediation plan.

## Scope

### In Scope
- Add 12 new `AuditEvent` values (password reset, admin actions, payment failures, stock changes, signature invalid, stock restore).
- Refactor `log_audit` to accept optional `Request`; add a service-layer entry without `Request`.
- Wire `log_audit` into 3 routers (auth/admin/payments) and 3 services (payments/orders/inventory).
- Redis-backed idempotency for `POST /orders` and MP preference creation: `Idempotency-Key` header, 24h TTL, cached response on replay.
- Tests asserting `log_audit` per path and idempotency replay.

### Out of Scope
- SIEM / log shipping; file-based audit storage.
- 2FA / MFA (F-024); rate-limit expansion (F-007).
- Webhook idempotency (covered by `security-fix-webhook-and-backdoor`).

## Capabilities

> Contract with sdd-spec. No existing specs cover audit or idempotency.

### New Capabilities
- `audit-logging`
- `idempotency-keys`

### Modified Capabilities
- None.

## Approach

**Audit.** Two helpers: `log_audit(event, request, details)` for routers; `log_audit_ctx(event, *, client_ip, method, path, details)` for services. Both emit identical JSON via the existing `audit` logger.

**Wiring.** Routers pass `request: Request`. Services receive an `AuditContext` dataclass plumbed from the router. Hot paths (`orders_helpers` stock decrement) use fire-and-forget `asyncio.create_task` so audit never blocks.

**Idempotency.** New `utils/idempotency.py` with `get_or_set(redis, key, ttl=86400, producer=...)` via Redis `SET NX`. Routers extract the header (UUID-validated), call the helper, return cached JSON on hit. Missing header → server-side fallback key.

## Affected Areas

| Area | Impact |
|------|--------|
| `audit_logger.py` | Add 12 events, split helpers, `AuditContext`. |
| 4 routers (auth/admin/payments/orders) | Wire audit; enforce `Idempotency-Key`. |
| 4 services (payments/orders/inventory/orders_helpers) | Wire audit; thread `AuditContext`. |
| `utils/idempotency.py` | New: Redis `SET NX` helper + header validation. |
| `tests/conftest.py` + tests/ | Extend autouse patch; new assertions. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Audit latency on order hot path | Medium | Fire-and-forget `create_task`; stdout only. |
| Service layer has no `Request` | Medium | `AuditContext` plumbed explicitly. |
| `Idempotency-Key` collisions across users | Low | Key = `<user_id>:<header_value>`. |
| Redis down breaks order creation | Low | Fail open with WARNING. |
| 400-line PR budget exceeded | High (forecast) | Split PR-1 (audit) + PR-2 (idempotency). |

## Rollback Plan

PR-1 (audit) revert: `log_audit` becomes a no-op; new enum is additive. PR-2 (idempotency) revert: endpoints stop enforcing `Idempotency-Key`; clients already sending it are unaffected. Both are merge-revert; no data migration.

## Dependencies

- Redis via `get_redis()` (already used for rate limiting + lockout).
- `tests/conftest.py` autouse fixture already patches `audit_logger.log_audit` — extend to `log_audit_ctx`.

## Success Criteria

- [ ] `log_audit` called in all 6 listed routers/services; no plain `logging.getLogger` for security events in auth/payments.
- [ ] 12 new events emit at documented paths; tests assert each.
- [ ] Duplicate `Idempotency-Key` on `POST /orders` and `POST /payments/create-preference` returns identical 200 within 24h; no second stock decrement or MP preference.
- [ ] Existing 109 tests pass; new tests cover audit + idempotency.
- [ ] PR-1 ≤400 LOC, PR-2 ≤400 LOC; `sdd-tasks` rejects single-PR merge on budget overrun.
- [ ] Audit latency on `POST /orders` p95 ≤ 2ms.
