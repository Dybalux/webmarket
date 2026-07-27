# Proposal: Auth Hardening — JWT Library, Password Policy, Reset Flow, Lockout

## Intent

PR #2 of the 6-PR remediation plan (audit 2026-06-15). Four auth findings, one PR:

- **F-004 (HIGH)**: `python-jose==3.5.0` unmaintained, known CVEs; confirmed installed (`security.py:3`), PyJWT absent from venv.
- **F-009 (HIGH)**: `UserRegister.password` (`models.py:133`) enforces only `min_length=8`.
- **F-015 (MEDIUM)**: No password-reset flow in `routers/auth.py`.
- **F-017 (MEDIUM)**: `/auth/token` has IP rate limiting (5/min) but no per-account lockout — brute-force below the rate limit is possible.

## Scope

### In Scope
- **F-004**: Swap `python-jose` → `PyJWT>=2.8.0` (`security.py`, `requirements.txt`); `jose.JWTError` → `jwt.PyJWTError`; explicit `algorithms=[HS256]`, never `none`.
- **F-009**: Pydantic password validator (register + reset): min 12 chars, upper/lower/digit/special; reject embedded common-password blocklist (offline).
- **F-015**: `POST /auth/forgot-password` + `POST /auth/reset-password`. Tokens: `secrets.token_urlsafe(32)`, SHA-256-hashed in Mongo, 1h expiry, single-use. Enumeration-resistant: identical 202 response for unknown emails. Delivery via existing Resend pattern.
- **F-017**: Redis per-account failed-login counter: 5 consecutive failures → 15-min lock; success resets. Complements existing IP `RateLimiter`.
- **Tests** for all four (same PR).

### Out of Scope
- `/auth/verify-email` (also under F-015) — deferred; user decision flagged below.
- PRs #3–#6 findings (input validation, infra, Decimal, audit logging); F-023 refresh-timing fix.
- Migrating existing passwords — policy applies at registration/reset only.

## Capabilities

### New Capabilities
- `auth-security`: JWT handling, password policy, password-reset flow, account lockout.

### Modified Capabilities
- None. Auth lives in `routers/auth.py` + `security.py`; no `service-layer` module touched.

## Approach

- **F-004**: Drop-in swap in `create_access_token`/`decode_access_token`. HS256 is standard JWS — tokens issued by python-jose stay valid; no forced logout.
- **F-009**: `@field_validator("password")` + module-level blocklist constant in `models.py`.
- **F-015**: New request schemas, token helpers in `security.py`, two endpoints, one email template.
- **F-017**: Lockout helpers (check/increment/reset) called from `/auth/token`.
- Redis access MUST be injectable — conftest `test_app` bypasses lifespan, so `FastAPILimiter`'s Redis is unavailable in tests.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `security.py` | Modified | PyJWT swap; reset-token + lockout helpers |
| `models.py:130-139` | Modified | Password validator; reset schemas |
| `routers/auth.py` | Modified | Lockout in `/token`; forgot/reset endpoints |
| `email_service.py` | Modified | Reset email template |
| `requirements.txt` | Modified | −`python-jose`, +`PyJWT>=2.8.0` |
| `tests/` | New | Unit + integration coverage |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **400-line budget**: audit ~300 excl. tests; with tests est. **330–420** | High | `ask-always` strategy → orchestrator asks user. Trims: compact blocklist, split tests to follow-up |
| JWT swap invalidates existing tokens | Low | Both standard JWS HS256, same `SECRET_KEY` |
| `PyJWTError` vs `JWTError` error-path drift | Medium | Map catch; tests assert identical 401s |
| Legitimate users locked out | Medium | 5-attempt/15-min window, clear detail, success resets |
| Lockout Redis unavailable in tests | Medium | Injectable client; conftest fake/override |
| Verify-email excluded from F-015 scope | — | **User decision needed** |

## Rollback Plan

Revert the PR. No DB migration; lockout keys expire via TTL; password policy affects new writes only; revert restores `python-jose` pin.

## Dependencies

- New: `PyJWT>=2.8.0`. Existing: `redis==6.4.0`, `fastapi-limiter`, Resend, `audit_logger`.

## Success Criteria

- [ ] `grep -rn "jose" --include="*.py"` zero matches; `python-jose` out of `requirements.txt`
- [ ] Pre-swap tokens still validate (same HS256 secret)
- [ ] Weak/common passwords → 422 with policy detail
- [ ] Forgot-password returns identical 202 for known/unknown emails
- [ ] Reset token: single-use, 1h expiry, never stored plaintext
- [ ] 5 failed logins → 15-min lock; success resets; IP `RateLimiter` intact
- [ ] `pytest tests/ -v --tb=short` exits 0

## References

- `openspec/audits/security-audit-2026-06-15.md` (F-004/009/015/017; PR #2 of 6)
- Exemplar: `openspec/changes/archive/2026-07-27-security-fix-webhook-and-backdoor/proposal.md`
