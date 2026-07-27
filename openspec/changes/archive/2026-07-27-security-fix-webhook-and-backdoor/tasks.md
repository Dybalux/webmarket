# Tasks: Security Fix — Webhook Validation & Dead-Code Backdoor Removal

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~130 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR (well within 400-line budget) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Configuration

- [x] 1.1 Add `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS: bool = False` to `Settings` class in `config.py` (after `MERCADOPAGO_WEBHOOK_SECRET`, line ~23).
  - Files: `config.py`
  - Estimate: ~2 lines (addition)
  - Done when: `settings.MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS` reads `False` by default from env.

- [x] 1.2 Document `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS` in `.env.example` under the Mercado Pago section.
  - Files: `.env.example`
  - Estimate: ~3 lines (comment + variable)
  - Done when: `.env.example` has the line with comment explaining it's for MP test-panel, default `false`.

## Phase 2: Webhook Validation Hardening (F-001)

- [x] 2.1 Rewrite `_validate_signature` in `services/payments.py` (lines 189–222) to raise `ForbiddenError` on invalid/missing/unsigned signatures instead of logging-and-returning. Three branches: (a) secret not configured + production → `ForbiddenError`; (b) missing sig + not allowed by env → `ForbiddenError`; (c) HMAC mismatch → `ForbiddenError`; (d) valid → return silently.
  - Files: `services/payments.py`
  - Estimate: ~25 lines (rewrite of existing 33-line function)
  - Done when: function raises `ForbiddenError` for all failure cases, returns silently on success, env var `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS` checked for dev escape hatch.

- [x] 2.2 Add `except ForbiddenError: raise` before the catch-all `except Exception` in `process_webhook` (line 180 in `services/payments.py`).
  - Files: `services/payments.py`
  - Estimate: ~2 lines (addition)
  - Done when: `ForbiddenError` raised by `_validate_signature` propagates past the catch-all to the global handler → 403 RFC 9457 response.

## Phase 3: Backdoor Removal (F-003)

- [x] 3.1 Delete `authenticate_user` function (lines 148–175) from `security.py`.
  - Files: `security.py`
  - Estimate: -28 lines (deletion)
  - Done when: `rg "def authenticate_user" security.py` returns nothing.

- [x] 3.2 Remove `UserLogin` from the import on line 8 of `security.py` (only used by `authenticate_user`).
  - Files: `security.py`
  - Estimate: ~1 line (edit)
  - Done when: import reads `from models import TokenData, UserRole` — no `UserLogin`. Verified: `routers/auth.py` imports `UserLogin` directly from `models`, not from `security`.

## Phase 4: Tests

- [x] 4.1 Unit test: `_validate_signature` with valid HMAC → no exception raised.
  - Files: `tests/unit/test_payments.py` (new file)
  - Estimate: ~15 lines
  - Done when: test passes with mocked `settings.MERCADOPAGO_WEBHOOK_SECRET` and correct HMAC.

- [x] 4.2 Unit test: `_validate_signature` with invalid HMAC → `ForbiddenError` raised.
  - Files: `tests/unit/test_payments.py`
  - Estimate: ~15 lines
  - Done when: test passes, asserts `ForbiddenError` with wrong signature.

- [x] 4.3 Unit test: `_validate_signature` with missing signature in production → `ForbiddenError` raised.
  - Files: `tests/unit/test_payments.py`
  - Estimate: ~15 lines
  - Done when: test passes, monkeypatches `settings.ENV = "production"` and `settings.MERCADOPAGO_WEBHOOK_SECRET = None`.

- [x] 4.4 Integration test: `process_webhook` end-to-end — bad `x-signature` → 403 RFC 9457 response.
  - Files: `tests/integration/test_webhook_security.py` (new file)
  - Estimate: ~25 lines
  - Done when: test mounts `routers/payments.router`, POSTs with bad `x-signature`, asserts `status_code == 403` and `Content-Type: application/problem+json`.

- [x] 4.5 Regression test: verify no `authenticate_user` imports remain in production code.
  - Files: N/A (grep verification — can be a simple pytest test or CI step)
  - Estimate: ~10 lines (pytest test that runs `rg` or scans imports)
  - Done when: test passes, confirms zero production imports of `authenticate_user`.

**Note**: Task 4.5 (fixture for deleted `authenticate_user`) is NOT needed — `tests/conftest.py` already provides `auth_user_dep` and `auth_admin_dep` with non-trivial tokens. Grep confirms zero imports of `authenticate_user` outside `security.py` itself (per Design ADR-4).

## Phase 5: Verification

- [x] 5.1 Run full test suite: `pytest --maxfail=1 --tb=short` — all tests pass (existing + new).
  - Files: N/A (test execution)
  - Estimate: 0 lines
  - Done when: `pytest` exits 0.

- [x] 5.2 Run `rg "authenticate_user" --include="*.py"` across repo — only matches in `openspec/` artifacts.
  - Files: N/A (verification)
  - Estimate: 0 lines
  - Done when: zero matches in production code and tests.

- [x] 5.3 Run `rg "admin@example.com" --include="*.py" --glob="!tests/*"` — zero matches.
  - Files: N/A (verification)
  - Estimate: 0 lines
  - Done when: no hardcoded admin email in source (except test fixtures if any).

- [x] 5.4 Manual review of git diff to confirm total changed lines < 400 (per D1 budget).
  - Files: N/A
  - Estimate: 0 lines
  - Done when: `git diff --stat` shows additions + deletions < 400.

## Work Unit Commits

| # | Commit Message | Tasks | Rationale |
|---|---------------|-------|-----------|
| 1 | `chore(config): add MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS setting` | 1.1, 1.2 | Enabling change — config first, no behavior change yet. |
| 2 | `fix(payments): make webhook signature validation blocking` | 2.1, 2.2 | Core security fix — tightly coupled, one commit. |
| 3 | `refactor(security): remove dead-code authenticate_user backdoor` | 3.1, 3.2 | Safety cleanup — deletion only, no behavior change. |
| 4 | `test(payments): cover webhook signature validation scenarios` | 4.1, 4.2, 4.3, 4.4, 4.5 | Tests for the behavior change in commit 2. |

Each commit should pass `pytest` on its own. Commit 2 changes behavior, so commit 4 (tests) should follow immediately — but commit 2 alone should not break existing tests (it only tightens validation, existing tests don't exercise the webhook path with bad signatures).

## Dependencies and Order

| Task | Depends On | Notes |
|------|-----------|-------|
| 1.1, 1.2 | None | Config first — other tasks read this setting. |
| 2.1 | 1.1 | `_validate_signature` reads `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS`. |
| 2.2 | 2.1 | Re-raise only matters after `_validate_signature` raises. |
| 3.1, 3.2 | None | Independent of webhook changes. |
| 4.1–4.4 | 2.1, 2.2 | Tests verify the new behavior. |
| 4.5 | 3.1 | Regression test confirms backdoor is gone. |
| 5.1–5.4 | All | Final verification. |

Tasks 3.1/3.2 could run in parallel with Phase 2 (different files, no shared state), but sequential is simpler for a single PR.

## Risks and Open Questions

| Risk | Mitigation |
|------|-----------|
| MP test-panel webhooks arrive without `x-signature` header (documented MP behavior) | Safe default: `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS=false` everywhere. Devs can opt-in. User will revisit after 6-PR plan (per Design ADR-3). |
| `_validate_signature` rewrite breaks existing webhook processing | Tests 4.1–4.4 cover all branches. Manual verification (5.1) confirms existing tests still pass. |
| `UserLogin` removal from `security.py` import breaks something | Verified: only `authenticate_user` used it in `security.py`. `routers/auth.py` imports `UserLogin` directly from `models`. |

### Open Questions (carried over from design)
- **MP test-panel default**: Should `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS` default to `true` in development? Deferred to post-6-PR-plan review. Safe default is `false` everywhere.
