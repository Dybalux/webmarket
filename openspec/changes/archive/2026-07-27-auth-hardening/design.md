# Design: Auth Hardening — JWT Swap, Password Policy, Reset Flow, Lockout

## Technical Approach

Four findings, one PR, ~330–420 lines. Drop-in `python-jose`→`PyJWT` swap in `security.py`; Pydantic v2 `@field_validator` password policy shared by registration and reset; forgot/reset endpoints with SHA-256-hashed single-use tokens in Mongo; per-account lockout in Redis via an injectable FastAPI dependency. Verify-email deferred (out of scope).

**Sources**: [Proposal](proposal.md) · [Spec](../../specs/auth-security/spec.md) · `openspec/audits/security-audit-2026-06-15.md`

## Architecture Decisions

### ADR-1: JWT swap mechanics

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Drop-in swap, keep `settings.ALGORITHM` | HS256 is standard JWS; pre-swap tokens stay valid | **Chosen** |
| Hardcode `"HS256"` | Removes config flexibility for zero gain | Rejected |
| Re-issue all tokens | Unnecessary — same algorithm and secret | Rejected |

Error mapping: `except JWTError` → `except jwt.PyJWTError` at `security.py:95`; 401 body unchanged. `jwt.encode(..., algorithm=...)`, `jwt.decode(..., algorithms=[...])` — never `none`.

### ADR-2: Password policy as Pydantic field validator

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `@field_validator` in `models.py` + module-level `COMMON_PASSWORDS` frozenset | Free 422 via existing `RequestValidationError` handler (RFC 9457-normalized); shared by `UserRegister` and `PasswordResetConfirm` | **Chosen** |
| Validator in router | Duplicated across register/reset | Rejected |
| External blocklist service | Network dependency for a static check | Rejected |

Policy: min 12, upper, lower, digit, special, not in compact embedded blocklist (~30 entries). Registration/reset only; login never checks policy.

### ADR-3: Reset tokens in Mongo, SHA-256 hashed

| Option | Tradeoff | Decision |
|--------|----------|----------|
| New `password_reset_tokens` collection, `sha256(token).hexdigest()` lookup key | High-entropy tokens need no bcrypt; O(1) `find_one` by hash | **Chosen** |
| Redis | Tokens must survive restarts; Mongo is the store of record | Rejected |
| bcrypt (like refresh tokens) | Forces cursor-scan lookup — the `/refresh` anti-pattern at `routers/auth.py:196` | Rejected |

Doc: `{token_hash, user_id, expires_at (1h), used: bool}`. Consume = atomic `find_one_and_update({token_hash, used: false, expires_at: {$gt: now}}, {$set: {used: true}})`. Enumeration-resistant: `forgot-password` always 202, identical body, one `find_one` either way.

### ADR-4: Lockout with injectable Redis dependency

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `get_redis` FastAPI dependency, overridden in tests via `app.dependency_overrides` | conftest `test_app` bypasses lifespan, so `FastAPILimiter`'s Redis is unreachable; DI override is the established conftest pattern | **Chosen** |
| Reuse `FastAPILimiter.redis` | Unavailable in tests; couples lockout to rate limiter | Rejected |
| Mongo counters | No native TTL-per-key lock windows | Rejected |

Keys: `login_fail:{username}` (INCR + TTL), `login_lock:{username}` (SETEX 900 at 5 failures). Success deletes both. Runs **after** the IP `RateLimiter` (kept as-is), before `verify_password`. Locked → 423 with remaining seconds. No fakeredis in dev-deps → conftest provides a minimal in-memory async fake (`get/setex/incr/delete/ttl`).

### ADR-5: Reset email via existing Resend pattern

New `send_password_reset_email(to_email, reset_url)` in `email_service.py`: same `EMAIL_ENABLED`/API-key guards, same non-raising `try/except`, same HTML style. Link: `{FRONTEND_URL}/reset-password?token={token}`. The `silence_side_effects` autouse fixture gains a second patch target.

## Data Flow

    POST /auth/forgot-password            POST /auth/token (login)
      │ find_one(email)                     │ RateLimiter (IP, 5/min)
      ├─ found ──► token=urlsafe(32)        │ get_redis (DI)
      │            store sha256, 1h         │ GET login_lock:{u} ──► 423 if set
      │            send_reset_email ──► 202 │ verify_password
      └─ not found ────────────────► 202    ├─ fail: INCR login_fail:{u}
      (identical body)                      │   ≥5 → SETEX login_lock 900 → 401
                                            └─ ok: DEL login_fail → tokens

    POST /auth/reset-password
      │ find_one_and_update(hash, unused, unexpired → used:true)
      ├─ None ──► 400 (expired/used/invalid)
      └─ doc ──► policy validation ──► update user hash ──► 200

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `security.py` | Modify | PyJWT swap; reset-token helpers; `get_redis` dep; `check_lockout/record_failure/clear_failures` |
| `models.py` | Modify | Password validator + `COMMON_PASSWORDS`; `ForgotPasswordRequest`, `PasswordResetConfirm` |
| `routers/auth.py` | Modify | Lockout in `/token`; `POST /forgot-password` (202), `POST /reset-password` |
| `email_service.py` | Modify | `send_password_reset_email` |
| `config.py` | Modify | `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=60`, `LOGIN_MAX_FAILURES=5`, `LOGIN_LOCKOUT_SECONDS=900` |
| `requirements.txt` | Modify | −`python-jose==3.5.0`, +`PyJWT>=2.8.0` |
| `tests/conftest.py` | Modify | Fake-redis fixture + `get_redis` override; patch new email fn |
| `tests/unit/test_password_policy.py` | Create | Validator cases |
| `tests/unit/test_jwt_pyjwt.py` | Create | Swap regression, alg-none, pre-swap token constant |
| `tests/integration/test_auth_hardening.py` | Create | Lockout + forgot/reset endpoint flows |

## Interfaces / Contracts

```python
# security.py
async def get_redis() -> redis.Redis: ...           # DI-overridable
async def check_lockout(r, username: str) -> int:   # 0 ok, >0 = seconds left
async def record_failure(r, username: str) -> None  # INCR; lock at threshold
async def clear_failures(r, username: str) -> None
def create_reset_token() -> str                     # secrets.token_urlsafe(32)
def hash_reset_token(token: str) -> str             # sha256 hexdigest

# models.py
class ForgotPasswordRequest(BaseModel):
    email: EmailStr
class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str  # shared policy validator
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Password policy matrix (short, no-digit, common, valid) | Direct model instantiation, assert `ValidationError` |
| Unit | JWT round-trip; `alg:none` → `PyJWTError`; pre-swap jose-signed token constant still decodes | Pure function tests |
| Unit | Lockout helpers: 5th failure locks, success resets, TTL expiry | In-memory fake redis |
| Integration | `/token`: 5 failures → 423; success resets; 401 bodies unchanged | `test_client` + `get_redis` override |
| Integration | forgot/reset: identical 202 known/unknown, single-use, expiry, weak-password 422 | `test_client` + mongomock collection |
| Regression | Zero `jose` imports; suite green | `grep -rn "jose" --include="*.py"`; `pytest tests/ -v --tb=short` |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration. Pre-swap tokens remain valid (standard HS256, same secret). Policy affects new writes only. Lockout keys self-expire via TTL. Rollback: revert PR; stray Redis keys are harmless.

## Open Questions

- [ ] None blocking. Blocklist kept compact (~30 entries) to protect the 400-line budget — expand post-merge if desired.
