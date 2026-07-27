# Design: Input Validation — Regex Sanitization, sort_by Whitelist, HTML Escape, Strict Models

## Technical Approach

Four findings, one PR, ~330–450 lines. Stdlib-only fixes at the exact sink points: `re.escape` wrapper for the two `search → $regex` sites, per-endpoint `sort_by` frozensets in `routers/admin.py`, `html.escape()` at every email interpolation, and a `BaseRequestModel(extra="forbid")` base for 14 input models. No new dependencies, no interface changes.

**Sources**: [Proposal](proposal.md) · [Spec](../../specs/input-validation/spec.md) · `openspec/audits/security-audit-2026-06-15.md`

## Architecture Decisions

### ADR-1: `escape_regex()` in `utils/sanitize.py`, implemented as `re.escape`

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `utils/sanitize.py` wrapping stdlib `re.escape` | `utils/` package exists (`utils/errors.py`); unit-testable; `re.escape` (3.7+) escapes exactly the spec's char class and is CPython-maintained | **Chosen** |
| Proposal's hand-rolled `re.sub` | Same semantics, more code to get wrong | Rejected (keep the `escape_regex` name, delegate to `re.escape`) |
| Inline at both call sites | Two copies drift | Rejected |

Applied at `routers/admin.py:135-139` and `services/products.py:110-114`. Empty/None `search` still skips `$or` — existing `if search:` guards untouched.

### ADR-2: Per-endpoint frozensets, validated BEFORE the `try:` block

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Module-level frozensets in `routers/admin.py` | Matches `COMMON_PASSWORDS` precedent (auth-hardening); whitelist next to its only consumer | **Chosen** |
| Shared config in `config.py` | Settings are env-driven; these are code constants | Rejected |

**Critical**: both listing endpoints wrap everything in `except Exception → 500` with no `except HTTPException: raise`. An `HTTPException(400)` raised *inside* `try` becomes a 500. Validation MUST run at function entry, before `try:`. Unknown field → `HTTPException(400, "Invalid sort field")`. Whitelists per spec: users `{created_at, username, email, role, updated_at}`, orders `{created_at, total_amount, status}`.

### ADR-3: `html.escape()` inline at each interpolation

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Stdlib `html.escape(str(x))` inline in both f-string templates | Zero deps; minimum blast radius; `quote=True` default escapes `"`/`'`, covering the `href="{reset_url}"` attribute context | **Chosen** |
| Jinja2 autoescaping | New dep + template files; proposal defers | Rejected |

Escapes `order_id`, `user_email`, `total_amount`, `payment_method` (`email_service.py:73-91`) and `reset_url` (line 164). Subject lines are plain text — no escaping. Non-raising `try/except` preserved.

### ADR-4: `BaseRequestModel` in `models.py`; `AdminProduct` excluded

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `BaseRequestModel(BaseModel)` with `extra="forbid"`; 14 input models inherit | One-line base; Pydantic v2 merges inherited `model_config` with each model's own, so `forbid` composes with `populate_by_name` | **Chosen** |
| Edit `model_config` per model | 14 duplicated edits; future models forget it | Rejected |

Inheriting: `UserRegister`, `UserLogin`, `ForgotPasswordRequest`, `PasswordResetConfirm`, `OrderCreate`, `CartItem`, `Address`, `BulkPriceUpdate`, `ProductUpdate`, `ComboCreate`, `ComboUpdate`, `ComboItem`, `PaymentSettingsUpdate`, `DynamicPricingUpdate`. **Excluded**: `AdminProduct` — dual-use (POST body *and* `model_validate(db_doc)` in `services/products.py`); `bulk_price_update` writes `updated_at` onto product docs, not a schema field, so `forbid` would 500 those DB reads. Response/DB models unchanged. Extras → 422 via the existing RFC 9457 handler (`utils/errors.py`).

### ADR-5: `Settings.extra` → `"ignore"`

Env-var supersets (Railway, `.env`, CI) must not crash boot; `ignore` drops unknown vars instead of `allow` storing them as attributes. `.env.example` stays source of truth.

## Data Flow

    GET /admin/users?search=..&sort_by=..      POST /auth/register {..}
      │ entry: sort_by ∈ frozenset? ─► 400       │ BaseRequestModel ─► 422
      │ try: escape_regex(search)                ▼ handler
      ▼ $regex literal                         email_service
    GET /products?search=..                      │ html.escape(str(x))
      │ services/products: escape_regex          ▼ resend.Emails.send
      ▼ $regex literal

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `utils/sanitize.py` | Create | `escape_regex(s: str) -> str` via `re.escape` |
| `routers/admin.py` | Modify | 2 frozensets + pre-`try` validation; `escape_regex` in users `$or` |
| `services/products.py` | Modify | `escape_regex(search)` in `list_products` |
| `email_service.py` | Modify | `html.escape()` all interpolations, both templates |
| `models.py` | Modify | `BaseRequestModel`; 14 models change base class |
| `config.py` | Modify | `extra="allow"` → `"ignore"` (line 56) |
| `tests/unit/test_sanitize.py` | Create | `escape_regex` cases |
| `tests/unit/test_strict_models.py` | Create | Extra-field 422 matrix; `AdminProduct` regression |
| `tests/unit/test_email_escaping.py` | Create | Escaped template output |
| `tests/integration/test_input_validation.py` | Create | Endpoint sort_by/search/422 flows |

## Interfaces / Contracts

```python
# utils/sanitize.py
def escape_regex(s: str) -> str:
    """Escape regex metacharacters so *s* matches literally in $regex."""
    return re.escape(s)

# models.py
class BaseRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

# routers/admin.py (module level)
ALLOWED_USER_SORT_FIELDS: frozenset[str] = frozenset(
    {"created_at", "username", "email", "role", "updated_at"})
ALLOWED_ORDER_SORT_FIELDS: frozenset[str] = frozenset(
    {"created_at", "total_amount", "status"})
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `escape_regex`: metachars (`C++`, `(a\|b)*`), empty/normal passthrough, output compiles | Pure function + `re.compile` round-trip |
| Unit | 14 models: extra field → `ValidationError`; valid payload passes; `AdminProduct(**doc_with_updated_at)` still validates | Direct instantiation (password-policy pattern) |
| Unit | Emails: `<script>` in `user_email` → `&lt;script&gt;` in captured `params["html"]`; `reset_url` quotes escaped | Real functions, `EMAIL_ENABLED=True`, mock `resend.Emails.send` + `database.get_collection` |
| Unit | `Settings.model_config["extra"] == "ignore"` | Config assertion |
| Integration | `/admin/users?sort_by=password_hash` → 400; `sort_by=username` → 200; orders whitelist → 400; `search=C%2B%2B` → 200 literal | `test_client` + `auth_admin_dep` |
| Integration | `POST /auth/register` + `{"extra":"y"}` → 422 problem+json | `test_client` + mongomock |
| Regression | Full suite green | `pytest tests/ -v --tb=short` |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration. 400-line budget risk is High: trim order is (1) parametrize unit matrices, (2) defer reset-email escaping, (3) `size:exception` only with orchestrator approval. Rollback: revert PR; one-way transforms, no data change.

## Open Questions

- [ ] `sort_order` accepts any int (motor raises outside {-1, 1} → 500). Out of scope; follow-up with `Literal[-1, 1]` if observed.
- [ ] Split `AdminProductCreate` from `AdminProduct` so creation forbids extras? Deferred — dual-use refactor belongs to service-layer work.
