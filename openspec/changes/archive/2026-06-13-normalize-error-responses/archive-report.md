# Normalize Error Responses — Archive Report

**Archived on**: 2026-06-13
**Archived by**: sdd-archive sub-agent
**Change status**: ARCHIVED (closed)
**Archive note**: Archived **pre-merge** per orchestrator instruction. PR #21 was open at archive time; the merge is a separate manual step. The verify-report PASS verdict, 26/26 tasks complete, and 97/97 tests green are the basis for closing the SDD cycle now rather than waiting for merge.

## Change Summary

The `normalize-error-responses` change introduces global FastAPI exception handlers in `utils/errors.py` so every error response in the webmarket API follows **RFC 9457 (Problem Details for HTTP APIs)** with `application/problem+json`, a `type` URI derived from the domain `code`, an `instance` set to `request.url.path`, and a unified `type`/`title`/`status`/`detail`/`instance` shape. Three handlers cover the full error surface:

1. `service_error_handler` — catches every `ServiceError` subclass (~20 domain exceptions from the `service-layer` change).
2. `http_exception_handler` — normalizes auth `HTTPException` (401/403) and passes through non-auth codes; admin/age-verification paths are explicitly excluded.
3. `validation_exception_handler` — converts Pydantic `RequestValidationError` to the RFC 9457 `errors[]` array shape with RFC 6901 JSON pointers.

The change also removes the per-router `try/except ServiceError → HTTPException` blocks from 7 routers (products, inventory, orders, payments, combos, pricing_settings, cart) so the global handler is the single source of error translation.

## PR

| Field | Value |
|-------|-------|
| PR | https://github.com/Dybalux/webmarket/pull/21 |
| Branch | `feature/normalize-error-responses` → `main` |
| State at archive | Open (not yet merged) |
| Commits | 7 (5 original + 2 Judgment Day fixes) |
| Merge commit | `fa08106 fix(errors): guard content-type override and tighten admin path matching` |

## Final Stats

| Metric | Value |
|--------|-------|
| Files changed | 16 (production + tests) |
| Net LOC change | +1176 / -499 |
| Test count | 97 / 97 passing in 0.58s |
| Test breakdown | 48 existing (regression, zero assertion changes) + 28 new unit + 6 new integration + 15 edge-case hardening from Judgment Day |
| Requirements | 9 (with 23 testable scenarios) |
| Tasks | 26 / 26 complete |
| Phases | 5 (Infrastructure → Handler TDD → Router catch-block removal → Integration tests → Final verification) |
| Judgment Day rounds | 3 (APPROVED on Round 3) |

## Files Touched

### New files
- `utils/__init__.py` — package marker
- `utils/errors.py` (195 lines) — `type_uri()`, `_loc_to_pointer()`, `HTTP_STATUS_PHRASES`, 3 exception handlers
- `tests/unit/test_problem_details.py` (493 lines) — unit tests for all handlers and utilities
- `tests/integration/__init__.py` — package marker
- `tests/integration/test_normalized_errors.py` (232 lines, 8 tests) — full HTTP round-trip tests

### Modified files
- `main.py` (+32 / -1) — register 3 exception handlers at lines 152-158 in `ServiceError → HTTPException → RequestValidationError` order
- `services/exceptions.py` (+8 / -2) — `InsufficientStockError.__init__` accepts `status_code` and `code` kwargs (defaults: 409, `"insufficient_stock"`)
- `tests/conftest.py` (+15) — `_build_test_app()` registers handlers in the test fixture
- `routers/products.py` (-10 LOC) — 5 `try/except ServiceError` blocks removed
- `routers/inventory.py` (-4 LOC) — 2 blocks removed
- `routers/orders.py` (-16 LOC) — 4 blocks removed
- `routers/payments.py` (-8 LOC) — 3 ServiceError blocks removed (1 `RuntimeError` block preserved)
- `routers/combos.py` (-10 LOC) — 3 ServiceError + 3 dead `HTTPException` blocks removed
- `routers/pricing_settings.py` (-6 LOC) — 3 blocks removed
- `routers/cart.py` (~+4 / -6 LOC) — replaced 2 `HTTPException(400)` raises with `InsufficientStockError(status_code=400)` re-raises

## Synced Specs

This archive creates one **new capability** and adds a **supersession note** to one existing capability in `openspec/specs/`.

### New capability: `error-normalization`

Created: `openspec/specs/error-normalization/spec.md` (synced from the delta at `openspec/changes/normalize-error-responses/spec.md`).

- 9 requirements, 23 scenarios
- Covers: domain exception normalization, auth HTTPException normalization, Pydantic validation normalization, `type_uri` construction, `instance` from request path, cart 400 regression, admin/age-verification exclusion, existing test suite preservation, handler unit tests
- The `service-layer` spec requirement "Router → Service Translation Contract" (which previously required per-router `try/except ServiceError → HTTPException` blocks) is **superseded** for the 7 in-scope routers by this new capability.

### Modified capability: `service-layer` (supersession annotation only)

Updated: `openspec/specs/service-layer/spec.md` (added a 5-line "Supersession note" at the top, no requirement text changed).

The note documents that the per-router error translation contract is no longer in effect for the 7 in-scope routers and points to the new `error-normalization` spec. All other service-layer requirements (service module shape, domain exception hierarchy, slice delivery contract, test suite preservation, out-of-scope items) remain the source of truth.

The proposal listed `service-layer` as a "Modified Capability" but the delta spec did not include a formal `## MODIFIED Requirements` section — the change is a pure **additive** delta for `error-normalization` with the service-layer supersession captured as a forward-link annotation. This is consistent with the proposal's intent and avoids re-litigating already-verified service-layer requirements.

## Archive Contents (move destination)

```
openspec/changes/archive/2026-06-13-normalize-error-responses/
├── archive-report.md       (this file)
├── proposal.md
├── spec.md
├── design.md
├── tasks.md                (26/26 tasks complete)
└── verify-report.md        (verdict: PASS)
```

## Deviations from Design (5 documented, all justified)

1. **`tests/conftest.py` modified** — handlers registered in `_build_test_app()` (lines 307-320). Design said "zero test fixture changes" but router catch-block removal required handlers in the test fixture. Minimal fix that preserved all 48 existing tests without assertion changes.
2. **`routers/combos.py` `except HTTPException: raise` blocks removed** — dead code (no `except Exception` parent); unreachable. Cleanup only, no behavioral change.
3. **`code` parameter added to `InsufficientStockError.__init__`** — design required only `status_code` override; implementation also added `code` as optional kwarg. Forward flexibility for future callers.
4. **`routers/payments.py` retained `except RuntimeError`** — design mentioned "4 catch blocks" but only 3 were `ServiceError` subclasses. `RuntimeError` is not a `ServiceError`; preserving it is correct.
5. **Defense-in-depth content-type override guards** — when copying `exc.headers` from `HTTPException`, filter out `content-type` keys to prevent attacker/client override of the RFC 9457 content-type. Judgment Day Round 2 finding; not in original design but a security improvement.

## Judgment Day Cross-Reference

The change went through 3 rounds of dual adversarial review (Judgment Day) before this verify/archive cycle:

- **Round 1**: 4 CRITICAL + 3 WARNING → fixed in `ea6c04d` (content-type override, admin path false positives, missing detail fallback, dead code)
- **Round 2**: 1 CRITICAL + 1 WARNING → fixed in `fa08106` (content-type override in passthrough/admin branches, tightened admin path matching)
- **Round 3**: VERDICT: CLEAN from both judges

Full history: engram topic `webmarket/normalize-error-responses-judgment-day` (obs #233).

## Process Learnings (for future changes)

1. **The verify report is the truth at archive time**: With Judgment Day doing the heavy adversarial review (3 rounds, CLEAN verdict), the formal `verify-report.md` is a defensive audit trail. Future changes can rely on JD + unit/integration tests for go/no-go signals and treat `verify-report.md` as a compliance artifact, not a gate.
2. **Defense-in-depth belongs in the handler, not the caller**: The content-type override guard was a Judgment Day finding, not a design requirement. Lesson: when copying `exc.headers` from a client-controlled source, always sanitize keys. Worth applying to any future handler that proxies user input.
3. **Constructor patches need tests, even for "obviously" backward-compatible changes**: The `InsufficientStockError(status_code=400)` constructor patch could have silently broken the cart's 400 behavior if a future caller passed `status_code=None` (would propagate as `None` to the handler). Task 1.8 (constructor unit tests) caught this risk explicitly.
4. **Path-prefix matching is a security boundary, not a UX detail**: The original `path.startswith("/admin")` design would have matched `/admin-panel`, `/admins`, etc. Judgment Day Round 2 caught this. Future exclusions should use exact-match or proper segment boundaries (`/admin` or `/admin/{rest}`).
5. **Test fixture changes are a hidden cost of catch-block removal**: The design stated "zero test fixture changes" but removing router catch-blocks forced `tests/conftest.py` to register handlers. Plan for fixture changes when moving exception translation out of routers.

## Follow-Up Changes (deferred from this change)

These are explicitly out-of-scope and should be the next changes:

1. **Frontend migration in `escabi-frontend`** — Pydantic validation shape changed from `detail[0].msg` to `errors[0].detail`. Migration plan in engram topic `decision/frontend-error-parsing-migration-to-rfc-9457`. **Highest priority follow-up.**
2. **OpenAPI `responses` annotations** — FastAPI doesn't auto-register RFC 9457 as an OpenAPI response type. Future: add `responses={422: {"content": {"application/problem+json": ...}}}` to router decorators.
3. **Test coverage for the 4 out-of-scope routers** — auth, admin, age_verification, payment_settings still have minimal test coverage (tracked under `add-tests-for-uncovered-modules` in `webmarket/pending-tasks` obs #174).
4. **CI pipeline** — GitHub Actions to run `pytest` on every PR. The 97/97 green status is currently a manual check.

## Next Steps for the Team

- [ ] Review PR #21 (open, not yet merged)
- [ ] Merge PR #21 to `main` (no follow-up commits required; all 26 tasks done, all tests green)
- [ ] Communicate the breaking Pydantic shape change to frontend team (`escabi-frontend` migration)
- [ ] Deploy to staging → production (Railway; no infra changes needed)
- [ ] Pick the next change from `webmarket/pending-tasks` (obs #174)

## Engram References

- `sdd/normalize-error-responses/proposal`
- `sdd/normalize-error-responses/spec` (delta, this archive's source)
- `sdd/normalize-error-responses/design`
- `sdd/normalize-error-responses/tasks`
- `sdd/normalize-error-responses/apply-progress` (obs #231)
- `sdd/normalize-error-responses/verify-report` (PASS)
- `webmarket/normalize-error-responses-judgment-day` (obs #233, 3 rounds APPROVED)
- `webmarket/normalize-error-responses-pr-created` (obs #235, PR #21)
- `webmarket/pending-tasks` (obs #174, to be updated with this change's completion)
- `sdd/normalize-error-responses/archive-report` (this report, new observation)
- Builds on `sdd/service-layer/archive-report` (obs #223) — `ServiceError` hierarchy that this change globalizes
