# Proposal: Input Validation — Regex Sanitization, sort_by Whitelist, HTML Escape, Pydantic extra="forbid"

## Intent

PR #3 of the 6-PR security remediation plan (audit 2026-06-15). Four input-validation findings, one PR:

- **F-008 (HIGH)**: NoSQL injection / ReDoS via `$regex` (`routers/admin.py:136-139`, `services/products.py:110-114`). User-supplied `search` strings flow directly into MongoDB `$regex` queries.
- **F-010 (HIGH)**: Admin `sort_by` field injection (`routers/admin.py:151, 217`). No whitelist on `sort_by` for `users` and `orders` listing endpoints.
- **F-018 (MEDIUM)**: HTML injection in `send_new_order_notification` email (`email_service.py:54-102`). F-string interpolation of `user_email`, `order_id`, `total_amount`, `payment_method` with no escaping.
- **F-026 (INFO)**: `Settings.extra="allow"` (`config.py:54-57`); request models in `models.py` lack `extra="forbid"`, so unexpected payload fields are silently ignored.

## Scope

### In Scope
- **F-008**: New `utils/sanitize.py` with `escape_regex(s)` helper. Sanitize `search` before every `$regex` use.
- **F-010**: Whitelist `ALLOWED_SORT_FIELDS` per endpoint in `routers/admin.py`. Reject unknown fields with `HTTPException(400)`.
- **F-018**: Escape all interpolated values in both order-notification and password-reset HTML templates with `html.escape()`.
- **F-026**: New `BaseRequestModel(BaseModel)` with `model_config = ConfigDict(extra="forbid")`; ~25 request models in `models.py` inherit from it. `Settings.extra="allow"` → `extra="ignore"`.
- **Tests** for all four (same PR).

### Out of Scope
- Migrating to MongoDB `$text` indexes (F-008 preferred approach; deferred — requires index management + lang config).
- Any of the 22 other findings (PRs #1, #2, #4–#6 cover them).
- Switching `email_service.py` to Jinja2 (would add template files; `html.escape` is the minimum-blast-radius fix).
- HTTP-level payload length caps (separate rate-limit work).

## Capabilities

### New Capabilities
- `input-validation`: regex sanitization, `sort_by` whitelists, HTML escaping in email templates, strict Pydantic request models.

### Modified Capabilities
- None. Validation layer only; `service-layer` and `auth-security` contracts preserved (F-018 fix to reset email is implementation detail).

## Approach

- **F-008**: `escape_regex(s) = re.sub(r'[.*+?^${}()|[\]\\]', r'\\\g<0>', s)`. Apply at every `search → $regex` site. Empty/None `search` skips the `$or` clause unchanged.
- **F-010**: Module-level `frozenset` per endpoint in `routers/admin.py`; check membership before `.sort()`; raise `HTTPException(400)` otherwise.
- **F-018**: `import html`; wrap every interpolation (`{html.escape(str(user_email))}`, etc.) in both `send_new_order_notification` and `send_password_reset_email`.
- **F-026**: New `BaseRequestModel(BaseModel)` in `models.py`; refactor ~25 request models to inherit. Response models keep current behavior (output, not input). `Settings.extra="ignore"`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `utils/sanitize.py` | New | `escape_regex()` helper |
| `routers/admin.py:135-139, 151, 217` | Modified | Regex sanitization + sort_by whitelist (users + orders) |
| `services/products.py:110-114` | Modified | Regex sanitization in `list_products` |
| `email_service.py:54-102, 147-181` | Modified | `html.escape()` all interpolations |
| `config.py:54-57` | Modified | `extra="allow"` → `extra="ignore"` |
| `models.py` (passim) | Modified | `BaseRequestModel` base; ~25 request models inherit |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **400-line budget**: ~330–450 LOC incl. tests | High | `ask-on-risk` strategy → orchestrator asks user. Trims: collapse test cases; defer F-018 reset-email fix. |
| `search` with regex meta-chars (e.g. `C++`) no longer matches | Low | Substring behavior is acceptable default. |
| `sort_by` whitelist too narrow, breaks admin UX | Med | Whitelist covers all currently-used fields; missing → 400 with clear message. |
| `extra="forbid"` breaks clients with undocumented fields | Med | Audit existing tests; 422 is loud and easy to fix. |
| Settings env-var typo silently dropped (was `allow`) | Low | `.env.example` is the source of truth. |

## Rollback Plan

Revert the PR. No DB migration. No data loss: `extra="forbid"` only affects new requests; `escape_regex` is one-way (no decoding). Sort whitelists are pure code paths.

## Dependencies

- None new. Stdlib `html` and `re` only.

## Success Criteria

- [ ] `grep -rn '\$regex' routers/ services/` shows every site guarded by `escape_regex`; no raw `search` interpolation
- [ ] `sort_by=<unknown>` returns 400 on `/admin/users` and `/admin/orders`
- [ ] Email templates render `<script>alert(1)</script>` literally (XSS escaped) for both order and reset emails
- [ ] `POST /auth/register` with extra field `{"foo": "bar"}` returns 422
- [ ] All 25+ request models in `models.py` inherit from `BaseRequestModel`
- [ ] `Settings.extra == "ignore"`; spurious env vars ignored, not stored
- [ ] `pytest tests/ -v --tb=short` exits 0

## References

- `openspec/audits/security-audit-2026-06-15.md` (F-008/010/018/026; PR #3 of 6)
- Exemplar: `openspec/changes/archive/2026-07-27-auth-hardening/proposal.md`
