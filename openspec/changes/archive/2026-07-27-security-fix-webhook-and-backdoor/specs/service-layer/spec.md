# Delta Spec: security-fix-webhook-and-backdoor

## ADDED Requirements

### Requirement: Webhook Signature Validation MUST Be Blocking

The MercadoPago webhook handler in `services/payments.py` MUST reject any webhook whose HMAC-SHA256 signature is missing, malformed, or invalid by raising `ForbiddenError`. The webhook MUST NOT be processed in those cases. The `_validate_signature` function MUST have three branches: (1) `MERCADOPAGO_WEBHOOK_SECRET` not configured + `ENV=production` → raise `ForbiddenError`; (2) signature missing/malformed/invalid → raise `ForbiddenError`; (3) valid signature → return silently.

The `process_webhook` function MUST explicitly re-raise `ForbiddenError` before any catch-all `except Exception` handler, so the error reaches the global exception handler and produces a 403 response to the client.

#### Scenario: Valid signature
- **GIVEN** a webhook arrives with `x-signature: <valid-hmac>` computed with the configured `MERCADOPAGO_WEBHOOK_SECRET`
- **WHEN** `_validate_signature` is called
- **THEN** signature verification succeeds and `process_webhook` continues to process the payment notification

#### Scenario: Invalid signature
- **GIVEN** a webhook arrives with `x-signature: <invalid-hmac>`
- **WHEN** `_validate_signature` is called
- **THEN** `ForbiddenError` is raised
- **AND** `process_webhook` re-raises it past the catch-all `except Exception`
- **AND** the client receives a 403 RFC 9457 response
- **AND** no order state mutation occurs

#### Scenario: Missing signature in production
- **GIVEN** `ENV=production` and `MERCADOPAGO_WEBHOOK_SECRET` is configured
- **WHEN** a webhook arrives without the `x-signature` header
- **THEN** the webhook is rejected with 403

#### Scenario: Missing secret in production
- **GIVEN** `ENV=production` and `MERCADOPAGO_WEBHOOK_SECRET` is not configured
- **WHEN** any webhook arrives
- **THEN** the webhook is rejected with 403 (signature cannot be validated without a secret)

#### Scenario: Catch-all does not swallow ForbiddenError
- **GIVEN** `process_webhook` has a catch-all `except Exception` handler
- **WHEN** `_validate_signature` raises `ForbiddenError`
- **THEN** an explicit `except ForbiddenError: raise` clause re-raises it before the catch-all
- **AND** the error propagates to the global `ServiceError` handler

### Requirement: Dead-Code Backdoor MUST Be Removed

The `authenticate_user` function in `security.py` MUST be removed entirely. It contains a hardcoded `fake_user_db` with admin credentials (`admin@example.com` / `123456`) that represents a critical security liability. No production router MUST import or call this function. If a mock user is needed for tests, it MUST be provided via a pytest fixture in `tests/`, not in production code.

#### Scenario: authenticate_user is removed
- **GIVEN** `security.py` is inspected after the change
- **WHEN** the file is read
- **THEN** the function `authenticate_user` is not defined
- **AND** `grep -r "authenticate_user" . --include="*.py"` returns zero matches outside `tests/`

#### Scenario: No router imports authenticate_user
- **GIVEN** the `routers/` directory
- **WHEN** `rg "from security import.*authenticate_user|import.*authenticate_user" routers/` runs
- **THEN** zero matches are found

#### Scenario: Existing tests do not depend on authenticate_user
- **GIVEN** the test suite
- **WHEN** `pytest` runs
- **THEN** no test imports or calls `authenticate_user` from `security`
- **AND** all tests pass (exit 0)

## Cross-cutting

### Rollback
Both changes are reversible with a single commit revert. No data migration is involved.

### Out of Scope
- F-002 (Decimal refactor) — separate PR (#5 in the 6-PR plan)
- F-004 through F-010 (HIGH findings) — separate PRs in the 6-PR plan
- All other audit findings — separate PRs

### Open Questions
- **MercadoPago test-panel webhooks**: The MP dashboard test tool sends webhooks without the `x-signature` header (documented behavior). This spec requires rejection in production. Development behavior is deferred — the user will revisit after the 6-PR plan completes. A safe default would be `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS=false` everywhere, with an explicit override for dev if needed.
