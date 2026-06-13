# Proposal: Normalize Error Responses (RFC 9457)

## Intent

Every router in webmarket translates domain exceptions to `HTTPException` individually — 100+ call sites, 11 routers, 6 distinct "ID inválido" messages, and the `code` field from the domain hierarchy never reaches HTTP. This change introduces **global FastAPI exception handlers** in `main.py` so that all error responses follow **RFC 9457 (Problem Details for HTTP APIs)** with a unified schema, consistent `type` URIs derived from domain `code` strings, and `application/problem+json` content-type. It does NOT modify routers, services, or frontend code.

## Personas / Affected Users

| Persona | Impact |
|---------|--------|
| Frontend devs (escabi-frontend) | Reads `detail` literally + branches on `status` → preserved. Pydantic array shape change (`detail[0].msg` → `errors[0].detail`) is **out of scope** — migration plan stored in engram. |
| External API integrators | New consistent error schema with `type`, `title`, `status`, `detail`, `instance`, `errors`. |
| Internal services (admin/age-verification) | Unchanged — keep existing custom handler. |

## Scope

### In Scope

- RFC 9457 global handler for all `ServiceError` subclasses (20 domain exceptions)
- RFC 9457 global handler for `HTTPException` (401/403 auth errors only — routers/auth)
- RFC 9457 handler for Pydantic `RequestValidationError` with `errors` array
- `type` URI builder utility: `code` → `https://api.altotrago.com/errors/{code}`
- `instance` populated from `request.url.path`
- Content-Type `application/problem+json` on all error responses
- New tests for all three handlers (strict TDD, test-first)
- 48 existing tests continue to pass after the change

### Out of Scope

| Item | Reason |
|------|--------|
| Router or service file changes | Handlers are global in `main.py` — zero router modifications |
| Frontend changes (escabi-frontend) | Separate change; migration plan at `decision/frontend-error-parsing-migration-to-rfc-9457` |
| Admin/age-verification `try/except Exception → 500` | Decision 1c — leave with custom handler, no change |
| `repositories/` layer | Not part of this change |
| i18n or localized messages | No change to `detail` string content |
| Duplicate `code` field in response body | Decision 4b — `type` URI derives from code; no duplicate field |

## Approach

Two global exception handlers registered in `main.py`:

1. **`@app.exception_handler(ServiceError)`** — catches all 20 domain exceptions. Reads `status_code`, `code`, and `detail`. Builds RFC 9457 problem+json with `type` (URI from code), `title` (HTTP reason phrase), `status`, `detail`, and `instance`.
2. **`@app.exception_handler(HTTPException)`** — wraps auth-related 401/403 into same RFC 9457 shape. Non-auth HTTPExceptions pass through unchanged.
3. **`@app.exception_handler(RequestValidationError)`** — converts Pydantic `detail[0].msg` to `errors[0].detail` array per RFC 9457 Section 3.2.

A `type_uri(code: str) → str` utility derives the `type` field from the domain exception `code` string (e.g., `"insufficient_stock"` → `"https://api.altotrago.com/errors/insufficient-stock"`).

Cart's `InsufficientStockError` at 400 is preserved (decision 2b) — the handler reads the status_code the exception carries; cart's override (400 instead of 409) is handled by the exception instance, not the handler.

## Open Questions

| Question | Status |
|----------|--------|
| Domain exceptions + auth via global RFC 9457 handler? | **RESOLVED** — 1c Hybrid |
| Cart stock keep 400? | **RESOLVED** — 2b |
| Expose `code` via `type` URI? | **RESOLVED** — 3a |
| RFC 7807 or RFC 9457? | **RESOLVED** — 4b (RFC 9457) |
| Frontend tolerance? | **RESOLVED** — 5b (reads `detail` + `status`; Pydantic array change out of scope) |

## Capabilities

> Contract with sdd-spec. Existing spec: `service-layer` (archived change).

### New Capabilities

- `error-normalization`: RFC 9457 problem+json error response format with global FastAPI exception handlers for `ServiceError`, `HTTPException` (auth), and `RequestValidationError`.

### Modified Capabilities

- `service-layer`: Domain exception handling changes from per-router `try/except` → `HTTPException` to global `@app.exception_handler(ServiceError)`. Spec requirement update: routers no longer need to translate exceptions individually.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Pydantic validation shape break (Home.jsx `detail[0].msg`) | Low | Frontend out of scope; migration plan documented in engram |
| Cart stock 400 preserved but handler assumes 409 | Low | Handler reads `status_code` from exception instance, not hardcoded |
| Admin/age-verification 500s unchanged | Low | Explicitly excluded (decision 1c); no regression risk |
| New handler tests insufficient | Medium | Strict TDD enforced; 3 handler tests + existing 48 pass |

## Rollback Plan

Remove the three `@app.exception_handler` registrations from `main.py`. Routers still contain their existing `try/except` → `HTTPException` blocks (unchanged by this change) — rollback restores per-router error handling with zero data loss.

## Dependencies

- `service-layer` change (archived) — the `services/exceptions.py` domain hierarchy this builds on
- `type` URI base URL: `https://api.altotrago.com/errors/` — must be configurable or templated for non-prod environments

## Acceptance Criteria

- [ ] All `ServiceError` subclasses return RFC 9457 `application/problem+json` with `type`, `title`, `status`, `detail`, `instance`
- [ ] Auth 401/403 `HTTPException` returns same RFC 9457 shape
- [ ] Pydantic `RequestValidationError` returns RFC 9457 with `errors` array (no `detail[0].msg`)
- [ ] `type` is a valid URI derived from domain `code`
- [ ] `status` in body matches HTTP status code
- [ ] `instance` reflects `request.url.path`
- [ ] 48 existing tests pass + new handler tests pass
- [ ] Zero router or service file changes required

## Reference

Builds on the `service-layer` change (archived) which extracted domain exceptions into `services/exceptions.py` with the `ServiceError` hierarchy. That change deferred error normalization; this change delivers it via global handlers.
