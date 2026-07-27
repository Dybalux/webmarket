# Tasks: Input Validation — Regex Sanitization, sort_by Whitelist, HTML Escape, Strict Models

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 350–450 (60-70 production + 200-280 tests) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Foundation) → PR 2 (Endpoint Hardening) → PR 3 (Email Escaping) |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Foundation: sanitize helper + strict Pydantic base + config | PR 1 | `pytest tests/unit/test_sanitize.py tests/unit/test_strict_models.py -v` | Unit: `escape_regex` pure function + model instantiation | `utils/sanitize.py`, `models.py` BaseRequestModel, `config.py` — revert removes forbid + sanitize helper |
| 2 | Endpoint hardening: sort whitelists + regex sanitization wired in | PR 2 | `pytest tests/integration/test_input_validation.py -v` | Integration: `test_client` with `auth_admin_dep` + mongomock | `routers/admin.py`, `services/products.py` — revert restores raw search/sort |
| 3 | Email HTML escaping | PR 3 | `pytest tests/unit/test_email_escaping.py -v` | Unit: mock `resend.Emails.send`, assert escaped params | `email_service.py` — revert restores f-string interpolation |

## Phase 1: Foundation

- [x] 1.1 Create `utils/sanitize.py` with `escape_regex(s: str) -> str` wrapping `re.escape`
- [x] 1.2 Add `BaseRequestModel(BaseModel)` to `models.py` with `model_config = ConfigDict(extra="forbid")`
- [x] 1.3 Change 14 request models to inherit from `BaseRequestModel`: `UserRegister`, `UserLogin`, `ForgotPasswordRequest`, `PasswordResetConfirm`, `OrderCreate`, `CartItem`, `Address`, `BulkPriceUpdate`, `ProductUpdate`, `ComboCreate`, `ComboUpdate`, `ComboItem`, `PaymentSettingsUpdate`, `DynamicPricingUpdate`
- [x] 1.4 Change `config.py` line 56: `extra="allow"` → `extra="ignore"`
- [x] 1.5 Create `tests/unit/test_sanitize.py`: metachars (`C++`, `(a|b)*`), empty/None passthrough, output compiles via `re.compile`
- [x] 1.6 Create `tests/unit/test_strict_models.py`: extra field → `ValidationError` for 14 models; valid payload passes; `AdminProduct(**doc_with_updated_at)` still validates

### PR 1 Scope (6 tasks)

- [x] 1.1 Create `utils/sanitize.py` with `escape_regex()` function using `re.escape()`
- [x] 1.2 Create `BaseRequestModel(BaseModel)` with `model_config = ConfigDict(extra="forbid")` in `models.py`
- [x] 1.3 Update `UserRegister` to inherit from `BaseRequestModel`
- [x] 1.4 Update `UserLogin` to inherit from `BaseRequestModel`
- [x] 1.5 Update `ForgotPasswordRequest` to inherit from `BaseRequestModel`
- [x] 1.6 Update `PasswordResetConfirm` to inherit from `BaseRequestModel`

## Phase 2: Core Implementation — Endpoint Hardening

- [x] 2.1 Add `ALLOWED_USER_SORT_FIELDS` frozenset to `routers/admin.py` (module level)
- [x] 2.2 Add `ALLOWED_ORDER_SORT_FIELDS` frozenset to `routers/admin.py` (module level)
- [x] 2.3 Add pre-`try` sort_by validation in users listing endpoint — `HTTPException(400)` before `try:` block
- [x] 2.4 Add pre-`try` sort_by validation in orders listing endpoint — `HTTPException(400)` before `try:` block
- [x] 2.5 Apply `escape_regex(search)` in users `$or` clause (`routers/admin.py:135-139`)
- [x] 2.6 Apply `escape_regex(search)` in `services/products.py:110-114` `list_products`
- [x] 2.7 Create `tests/integration/test_input_validation.py`: `/admin/users?sort_by=password_hash` → 400; `sort_by=username` → 200; orders whitelist → 400; `search=C%2B%2B` → 200 literal match

## Phase 3: Core Implementation — Email Escaping

- [x] 3.1 Import `html` in `email_service.py`
- [x] 3.2 Escape all interpolations in `send_new_order_notification`: `user_email`, `order_id`, `total_amount`, `payment_method`
- [x] 3.3 Escape `reset_url` in `send_password_reset_email`
- [x] 3.4 Create `tests/unit/test_email_escaping.py`: `<script>alert(1)</script>` → `&lt;script&gt;` in captured `params["html"]`; normal values pass through; special HTML chars escaped

## Phase 4: Integration Verification

- [x] 4.1 Run full test suite: `pytest tests/ -v --tb=short` — exit 0
- [x] 4.2 Verify `grep -rn '\$regex' routers/ services/` shows every site guarded by `escape_regex`
- [x] 4.3 Verify all 14 request models inherit from `BaseRequestModel`
- [x] 4.4 Verify `Settings.extra == "ignore"` via config assertion

## Phase 5: Cleanup

- [x] 5.1 Review: no raw `search` interpolation in `$regex` paths
- [x] 5.2 Review: `AdminProduct` excluded from `BaseRequestModel` (dual-use model)
- [x] 5.3 Verify `sort_by` error messages are clear and actionable

## Phase 6: Coverage Gap Remediation (verify follow-up)

- [x] 6.1 Add `TestEmptySearchSkipsRegex` to `tests/integration/test_input_validation.py` — empty/absent search returns all results (S1.2)
- [x] 6.2 Add `TestSettingsIgnoresUnknownEnvVars` to `tests/unit/test_strict_models.py` — Settings accepts unknown env vars without error (S4.3)
- [x] 6.3 Add `TestResponseModelsAcceptExtraFields` to `tests/unit/test_strict_models.py` — response model accepts extra fields (S4.4)
