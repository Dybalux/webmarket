# Tasks: Auth Hardening

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 380–460 (prod ≈ 250, tests ≈ 130–210) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | PR | Test command | Harness | Rollback |
|------|------|----|-------------|---------|----------|
| 1 | Foundation + security core | 1 | `pytest tests/unit/ -v` | Unit only | config, requirements, models, security.py |
| 2 | Router + email integration | 2 | `pytest tests/integration/test_auth_hardening.py -v` | test_client + fake Redis | routers/auth.py, email_service.py, conftest |
| 3 | Full suite + cleanup | 3 | `pytest tests/ -v --tb=short` | Full suite | test additions only |

## Phase 1: Foundation

- [x] 1.1 `config.py`: add `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=60`, `LOGIN_MAX_FAILURES=5`, `LOGIN_LOCKOUT_SECONDS=900`
- [x] 1.2 `requirements.txt`: remove `python-jose==3.5.0`, add `PyJWT>=2.8.0`
- [x] 1.3 `models.py`: add `COMMON_PASSWORDS` frozenset (~30) + `@field_validator("password")` on `UserRegister` (min 12, upper/lower/digit/special, not-common)
- [x] 1.4 `models.py`: add `ForgotPasswordRequest` and `PasswordResetConfirm` schemas (reuses password validator)

## Phase 2: Core Implementation

- [x] 2.1 `security.py`: swap `from jose import JWTError, jwt` → `import jwt as pyjwt`; update encode/decode calls; catch `pyjwt.PyJWTError` instead of `JWTError` — same 401 body
- [x] 2.2 `security.py`: add `create_reset_token()` (secrets.token_urlsafe) and `hash_reset_token()` (sha256 hexdigest)
- [x] 2.3 `security.py`: add `get_redis()` async DI dependency, `check_lockout()`, `record_failure()`, `clear_failures()` using `login_fail:{u}` + `login_lock:{u}` keys
- [x] 2.4 `email_service.py`: add `send_password_reset_email(to_email, reset_url)` following existing Resend pattern

## Phase 3: Integration

- [x] 3.1 `routers/auth.py`: wire lockout in `/auth/token` — check_lockout → 423, record_failure on fail, clear_failures on success
- [x] 3.2 `routers/auth.py`: add `POST /forgot-password` — always 202, identical body for known/unknown emails
- [x] 3.3 `routers/auth.py`: add `POST /reset-password` — atomic token consume, policy check, password update

## Phase 4: Testing

- [x] 4.1 `tests/unit/test_jwt_pyjwt.py`: pre-swap jose token decodes; alg:none rejected; round-trip matches claims
- [x] 4.2 `tests/unit/test_password_policy.py`: strong accepted; short/common/missing-class rejected (422); pre-policy passwords not re-checked
- [x] 4.3 `tests/integration/test_auth_hardening.py`: forgot/reset flows — 202 enum-resistant, valid token ok, expired/reused rejected, weak password 422
- [x] 4.4 `tests/integration/test_auth_hardening.py`: lockout — 5 failures → 423, success resets, expiry simulated
- [x] 4.5 `tests/conftest.py`: add fake Redis fixture + `get_redis` override + patch `send_password_reset_email`

## Phase 5: Cleanup

- [x] 5.1 `grep -rn "jose" --include="*.py"` — zero matches in prod code
- [x] 5.2 `pytest tests/ -v --tb=short` — suite green
- [x] 5.3 Verify `python-jose` absent from requirements and pip list
