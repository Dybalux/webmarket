schema: gentle-ai.verify-result/v1
evidence_revision: sha256:22ca3e44ab9772180ae21f79dda2a478440904e770bee26d11fc39b086d53a02
verdict: pass
blockers: 0
critical_findings: 0
requirements: 2/2
scenarios: 8/8
test_command: pytest tests/ -v --tb=short
test_exit_code: 0
test_output_hash: sha256:e01dca5343b204b0b60eb658f4ca48fee436d375666055441cb3ce2f40fc1cf9
build_command: .venv/bin/python -c "import main; print('import OK')"
build_exit_code: 0
build_output_hash: sha256:73e65cba19528ade3fd463248a9ba2c44e92c41810caef6a0bba624cefc54219

# Verify Report: security-fix-webhook-and-backdoor

## Verdict
- **Status**: PASS-WITH-WARNINGS
- **Date**: 2026-06-15
- **Reviewer**: sdd-verify (sub-agent)

## Summary
- Spec scenarios verified: 8/8
- Tests run: 109 (passing: 109, failing: 0, skipped: 0)
- Critical issues: 0
- Warnings: 1
- Suggestions: 2
- Budget: 406 lines (6 over 400 — user accepted `size:exception`)

## Scenario Validation

### Scenario 1: Valid signature
- **Status**: ✅ PASS
- **Test mapping**:
  - `tests/unit/test_payments.py::test_validate_signature_valid_hmac` — unit: valid HMAC → no exception raised
  - `tests/integration/test_webhook_security.py::test_webhook_valid_signature_no_exception` — integration: valid sig → 200
  - `tests/integration/test_webhook_security.py::test_webhook_valid_signature_with_x_request_id` — integration: valid sig + x-request-id → 200
- **Evidence**: All 3 tests pass. `_validate_signature` returns silently on valid HMAC. Integration test confirms the request proceeds past signature check (200 response, not 403).
- **Notes**: None.

### Scenario 2: Invalid signature
- **Status**: ✅ PASS
- **Test mapping**:
  - `tests/unit/test_payments.py::test_validate_signature_invalid_hmac` — unit: HMAC mismatch → `ForbiddenError`
  - `tests/unit/test_payments.py::test_validate_signature_malformed_header` — unit: missing ts/v1 → `ForbiddenError`
  - `tests/integration/test_webhook_security.py::test_webhook_bad_signature_returns_403` — integration: bad sig → 403 RFC 9457
- **Evidence**: Unit tests confirm `ForbiddenError` raised with correct message. Integration test confirms the error propagates past the catch-all `except Exception` in `process_webhook` (line 181-182: `except ForbiddenError: raise`) to produce a 403 with `Content-Type: application/problem+json`.
- **Notes**: The integration test is the critical one — it proves the catch-all fix (engram #268 sub-finding) works end-to-end.

### Scenario 3: Missing signature in production
- **Status**: ✅ PASS
- **Test mapping**:
  - `tests/unit/test_payments.py::test_validate_signature_missing_in_production` — unit: ENV=production, no x-signature → `ForbiddenError`
  - `tests/integration/test_webhook_security.py::test_webhook_missing_signature_in_production_403` — integration: POST without x-signature in production → 403
- **Evidence**: Both tests pass. Unit test confirms `ForbiddenError("Missing webhook signature.")` raised. Integration test confirms 403 response at HTTP level.
- **Notes**: None.

### Scenario 4: Missing signature in development (opt-in)
- **Status**: ✅ PASS
- **Test mapping**:
  - `tests/unit/test_payments.py::test_validate_signature_unsigned_allowed_in_dev` — unit: ENV=development, `ALLOW_UNSIGNED_WEBHOOKS=true` → no exception
  - `tests/unit/test_payments.py::test_validate_signature_unsigned_rejected_in_dev_when_disabled` — unit: ENV=development, `ALLOW_UNSIGNED_WEBHOOKS=false` → `ForbiddenError`
- **Evidence**: Both tests pass. The env var `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS` is read correctly:
  - `config.py:24`: `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS: bool = False` (safe default)
  - `services/payments.py:216-224`: checked only when `ENV != "production"` AND `x_signature` is falsy
- **Notes**: The `test_validate_signature_unsigned_allowed_in_dev` test confirms the dev escape hatch works for MP test-panel. Default is `false` (safe).

### Scenario 5: `authenticate_user` is removed
- **Status**: ✅ PASS
- **Test mapping**:
  - `tests/unit/test_payments.py::test_authenticate_user_not_in_security_module` — regression: `hasattr(security, "authenticate_user")` is False
- **Evidence**:
  - `security.py` has 146 lines (was 176). Lines 148-175 (the entire `authenticate_user` function including `fake_user_db`) are deleted.
  - `security.py:8`: import reads `from models import TokenData, UserRole` — `UserLogin` removed.
  - `rg "def authenticate_user" --type py`: 0 matches in production code.
  - `rg "fake_user_db" --type py`: 0 matches.
  - `rg "admin@example\.com" --type py`: 0 matches.
- **Notes**: None.

### Scenario 6: Existing tests do not depend on `authenticate_user`
- **Status**: ✅ PASS
- **Test mapping**: Full test suite run (109/109 passing)
- **Evidence**:
  - `rg "authenticate_user" --type py`: matches ONLY in `tests/unit/test_payments.py` (the regression test itself, 6 lines referencing the name in assertions/comments). Zero imports of `authenticate_user` from `security` in any test.
  - `rg "from security import.*authenticate_user|import.*authenticate_user" routers/`: 0 matches.
  - All 109 tests pass, including 97 pre-existing tests.
- **Notes**: The `tests/conftest.py` already provides `auth_user_dep` and `auth_admin_dep` fixtures — no test needed the deleted function.

### Scenario 7: Production without `MERCADOPAGO_WEBHOOK_SECRET` rejects all webhooks
- **Status**: ✅ PASS
- **Test mapping**:
  - `tests/unit/test_payments.py::test_validate_signature_missing_secret_in_production` — unit: secret=None, ENV=production → `ForbiddenError("not configured")`
- **Evidence**:
  - `services/payments.py:206-212`: Branch 1 of `_validate_signature` — `if not secret:` → `if settings.ENV == "production":` → `raise ForbiddenError("Webhook secret not configured in production.")`
  - Test passes with `monkeypatch.setattr("services.payments.settings.MERCADOPAGO_WEBHOOK_SECRET", None)` and `ENV=production`.
- **Notes**: None.

### Scenario 8: No backdoor remnants in production code
- **Status**: ✅ PASS
- **Test mapping**: Grep verification (manual)
- **Evidence**:
  - `rg "admin@example\.com" --type py`: 0 matches ✅
  - `rg "fake_user_db" --type py`: 0 matches ✅
  - `rg "123456" -wn --type py`: 7 matches, ALL in `tests/integration/test_webhook_security.py` — these are MercadoPago payment IDs in webhook URLs (`id=123456`), NOT passwords. ✅
  - `rg "authenticate_user" --type py`: only in `tests/unit/test_payments.py` regression test. ✅
- **Notes**: None.

## Code Review Findings

### CRITICAL
- (none)

### WARNING

1. **`process_webhook` catch-all still logs and silently swallows unexpected exceptions**
   - **File**: `services/payments.py:183-184`
   - **Issue**: After the explicit `except ForbiddenError: raise` at line 181-182, the catch-all `except Exception as exc` at line 183 logs the error but does NOT re-raise it. This means if the MercadoPago SDK call (`_get_sdk().payment().get(payment_id)`) fails, or if MongoDB operations fail, the webhook endpoint returns 200 silently. This was the pre-existing behavior (not introduced by this change), but it's worth noting: a production webhook that fails mid-processing will appear successful to MercadoPago, which won't retry it.
   - **Severity**: WARNING — this is a design decision outside the scope of this change (the spec explicitly says "minimal blast radius"). The catch-all was there before; the fix correctly ensures `ForbiddenError` escapes it. Recommend addressing in a future PR (e.g., the 6-PR plan's service-layer hardening).
   - **Scope**: Pre-existing, not introduced by this change.

### SUGGESTION

1. **Integration test does not verify `process_webhook` catch-all behavior for non-ForbiddenError exceptions**
   - **File**: `tests/integration/test_webhook_security.py`
   - **Issue**: The integration tests cover the happy path (valid sig → 200) and the `ForbiddenError` path (bad sig → 403), but there's no test that mocks a downstream failure (e.g., MongoDB error) to confirm the catch-all still handles it correctly. Since the catch-all was modified (re-raise added before it), a regression test for the catch-all's non-ForbiddenError behavior would be valuable.
   - **Severity**: SUGGESTION — low risk since the catch-all is unchanged for non-ForbiddenError exceptions, but good hygiene for a security-critical path.

2. **Consider adding a `# SECURITY` comment on the `except ForbiddenError: raise` line**
   - **File**: `services/payments.py:181`
   - **Issue**: The line `except ForbiddenError: raise` is the critical security gate that prevents the catch-all from swallowing auth failures. A future developer unfamiliar with the history might remove it during a refactor. A brief inline comment (e.g., `# SECURITY: must propagate past catch-all — see spec F-001`) would make the intent self-documenting.
   - **Severity**: SUGGESTION — defensive coding practice.

## Grep Verification

- `rg "admin@example\.com" --type py`: **0 matches** (expected: 0) ✅
- `rg "authenticate_user" --type py`: **6 matches**, all in `tests/unit/test_payments.py` (regression test comments/assertions). Zero in production code. ✅
- `rg "fake_user_db" --type py`: **0 matches** (expected: 0) ✅
- `rg "123456" -wn --type py`: **7 matches**, all in `tests/integration/test_webhook_security.py` — MercadoPago payment IDs in webhook query params, not passwords. ✅

## Budget Analysis

- Total changed lines: 406 (362 additions + 44 deletions)
- 400-line budget: 6 lines over (1.5%)
- Decision: user accepted `size:exception` for PR #1; PR #2 (tests) is the cause of overage

Per-commit line counts (additions + deletions):
- `40664f5` (config): 5 lines (+5/-0)
- `b0d4954` (fix): 58 lines (+44/-14)
- `6d2f03b` (refactor): 31 lines (+1/-30)
- `a0d400e` (test): 312 lines (+312/-0)

## PR Split Validation (B option)

- **PR #1** (first 3 commits: `40664f5`, `b0d4954`, `6d2f03b`): 94 lines total (+50/-44). Security fix in production code. Well within 400-line budget.
- **PR #2** (4th commit: `a0d400e`): 312 lines total (+312/-0). Test coverage. Within 400-line budget.
- Both individually within budget.
- Recommendation: proceed with PR split as planned.

## Open Questions

Carry-over from spec/design:
- **MP test-panel webhooks behavior**: Deferred to post-6-PR-plan review. Current implementation has safe default (`MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS=false`). User will revisit whether dev should default to `true`.
- No new open questions found during verification.

## Recommendation

**PASS-WITH-WARNINGS**: The change is ready for the user's push/PR decision. All 8 spec scenarios are verified with passing tests and code review evidence. The single WARNING is about a pre-existing catch-all behavior (not introduced by this change) that should be addressed in a future PR. The 2 SUGGESTIONS are minor defensive-coding improvements.

The orchestrator should proceed with `branch-pr` skill + `chained-pr` for the 2-PR split:
- PR #1: commits `40664f5` → `b0d4954` → `6d2f03b` (config + fix + refactor)
- PR #2: commit `a0d400e` (tests)

## References
- Proposal: openspec/changes/security-fix-webhook-and-backdoor/proposal.md
- Spec: openspec/changes/security-fix-webhook-and-backdoor/specs/service-layer/spec.md
- Design: openspec/changes/security-fix-webhook-and-backdoor/design.md
- Tasks: openspec/changes/security-fix-webhook-and-backdoor/tasks.md
- Apply progress: engram #273
- Source audit: openspec/audits/security-audit-2026-06-15.md
