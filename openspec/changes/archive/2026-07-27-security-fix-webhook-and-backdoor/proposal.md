# Proposal: Security Fix — Webhook Validation & Dead-Code Backdoor

## Intent

Two CRITICAL findings from the 2026-06-15 security audit must be fixed immediately:
1. **F-001**: Webhook signature validation is non-blocking — forged payment webhooks can alter order state.
2. **F-003**: Dead-code `authenticate_user` contains hardcoded admin credentials (`admin@example.com` / `123456`) — a dangerous time-bomb if accidentally re-wired by a refactor.

## Scope

### In Scope
- **F-001**: Make `_validate_signature` raise `ForbiddenError` (403) on invalid / missing signature. Require `MERCADOPAGO_WEBHOOK_SECRET` in production; reject webhooks without it.
- **F-001**: Fix `process_webhook` to let `ForbiddenError` propagate past its catch-all `except Exception`.
- **F-003**: Delete `authenticate_user` function (lines 148–175) from `security.py`.
- **Tests**: Confirm invalid signature → 403. Confirm no test / import relies on `authenticate_user`.

### Out of Scope
- **F-002** (Decimal refactor) — separate PR (#5), cross-cutting.
- **F-004 → F-026** — covered by PRs #2–#6 in the audit's remediation plan.
- **No** DB migration, no config changes beyond `MERCADOPAGO_WEBHOOK_SECRET` enforcement logic.
- **No** rate limiting (F-007), monkey creds in `docker-compose.yaml` (F-013), or CORS hardening (F-005).

## Capabilities

### Modified Capabilities
- `service-layer`: `process_webhook` error contract changes — `_validate_signature` now raises `ForbiddenError` on invalid signature instead of logging-and-continuing. Router (`routers/payments.py`) already delegates to `process_webhook`; the global `ServiceError` handler produces the 403.

### New Capabilities
- None. Both fixes operate within the existing `ForbiddenError` exception and `service-layer` spec.

## Approach

**F-001**: Rewrite `_validate_signature` to three branches:
1. Secret not configured + `ENV=production` → raise `ForbiddenError`.
2. Signature missing / malformed / invalid → raise `ForbiddenError`.
3. Valid signature → return (silent success).

Wrap `_validate_signature()` call in `process_webhook` with a specific `except ForbiddenError: raise` before the catch-all `except Exception`.

**F-003**: Delete `authenticate_user` (28 lines). Remove `UserLogin` from the import (if no other consumer exists — verify at apply time).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `services/payments.py:189-222` | Modified | `_validate_signature` raises `ForbiddenError` instead of logging |
| `services/payments.py:109-181` | Modified | `process_webhook` lets `ForbiddenError` propagate |
| `security.py:8` | Modified | Remove `UserLogin` import if unused after deletion |
| `security.py:148-175` | Removed | `authenticate_user` function deleted |
| `tests/` | New | Test: invalid signature → 403; `authenticate_user` not imported |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `process_webhook` catch-all swallows the new `ForbiddenError` | Low | Explicit `except ForbiddenError: raise` before the general handler |
| MP test-panel webhooks arrive without x-signature header | Medium | Audit documents this as "normal in MP panel tests" — allow in development, reject in production |
| `UserLogin` import removal breaks something else in `security.py` | Low | Verify at apply time; grep for `UserLogin` usage in the module |

## Rollback Plan

Revert the commit. Both changes are isolated (`services/payments.py` + `security.py`) — no shared state, no DB migration, no config changes that survive a revert.

## Dependencies

- `ForbiddenError` already exists in `services/exceptions.py` (status 403).
- Global `@app.exception_handler(ServiceError)` in `main.py` already handles `ForbiddenError` → RFC 9457.

## Success Criteria

- [ ] `curl -X POST /payments/webhook` with invalid `x-signature` → 403 + RFC 9457 body
- [ ] `curl -X POST /payments/webhook` with valid signature → 200, order processed
- [ ] `ENV=production` + unset `MERCADOPAGO_WEBHOOK_SECRET` → webhook returns 403
- [ ] `grep -r "authenticate_user" *` returns zero matches
- [ ] All existing tests pass (`pytest` exit 0)
- [ ] `grep -r "admin@example.com" *.py` returns zero matches (except tests if a fixture exists)

## References

- **Audit report**: `openspec/audits/security-audit-2026-06-15.md` (F-001, F-003)
- **Engram**: topic `sdd/audit/security-audit-2026-06-15`, observation #264
- **Affected code**: `services/payments.py:189-222`, `security.py:148-175`
- **Remediation PR plan**: PR #1 of 6 (~50 estimated lines)
