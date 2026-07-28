# Proposal: Infra Hardening — CORS, Headers, Docs, Docker, ENV, .env, HTTPS

## Intent

PR #4 of the 6-PR security remediation plan (audit 2026-06-15). Eight infrastructure findings, one PR:

- **F-005 (HIGH)**: CORS allows all methods/headers; `*` appended to origins in dev (`main.py:74-103`).
- **F-006 (HIGH)**: No HTTP security headers — no CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
- **F-011 (MEDIUM)**: Swagger/ReDoc exposed in production (`main.py:65-66`).
- **F-012 (MEDIUM)**: Dockerfile runs as root, no `USER` directive (`Dockerfile:1-27`).
- **F-013 (MEDIUM)**: docker-compose exposes MongoDB/Redis on host ports, hardcoded creds, no Redis password, `:latest` tags (`docker-compose.yaml:22-41`).
- **F-016 (MEDIUM)**: `ENV` defaults to `development`; `uvicorn.run(reload=True)` keyed off the default (`config.py:45`, `main.py:274-275`).
- **F-021 (LOW)**: `.env` perms documented but not enforced; needs `chmod 600` plus `.env.example` guidance.
- **F-025 (INFO)**: No HTTPS redirect middleware when `ENV=production`.

## Scope

### In Scope
- **F-005**: Drop `*` branch entirely; hardcode `allow_methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"]` and `allow_headers=["Authorization","Content-Type","X-Requested-With"]`. Origins remain an explicit list (current 7 + `FRONTEND_URL`).
- **F-006**: New `SecurityHeadersMiddleware` (Starlette `BaseHTTPMiddleware`) in `main.py`. Sets `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: geolocation=(), microphone=(), camera=()`. HSTS only when `ENV=production` (no `max-age` on dev).
- **F-011**: `docs_url=None, redoc_url=None, openapi_url=None` when `ENV == "production"`.
- **F-012**: Add non-root `appuser` (`adduser -D appuser`, `chown -R appuser /app`, `USER appuser`).
- **F-013**: Remove host `ports:` for Mongo/Redis; read creds from `.env` (`MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`, `REDIS_PASSWORD`); pin `mongo:7.0` and `redis:7.2-alpine`; add `command: --requirepass ${REDIS_PASSWORD}`.
- **F-016**: Make `ENV` required — no default, fail-fast at `Settings()` instantiation if unset. Drop the dev/reload branch in `main.py`; bind to `127.0.0.1` in production (Cloudflare Tunnel terminates TLS).
- **F-021**: Add a `chmod 600 .env` step to `README.md` and a `Permissions` section in `.env.example`. Local `.env` already 600 (verified 2026-07-27); add `Makefile` target for fresh clones.
- **F-025**: Add `HTTPSRedirectMiddleware` conditionally (`if settings.ENV == "production"`). Trust `X-Forwarded-Proto` via Starlette's `forwarded_allow_ips` when behind Cloudflare.
- **Tests** for F-005, F-006, F-011, F-016, F-025 (httpx-level). Docker/.env fixes verified by CI lint / shell test.

### Out of Scope
- **F-002** (Decimal refactor) — PR #5.
- **F-007** (rate limiting expansion), **F-014** (audit logging), **F-019** (stale `config.yaml` docs), **F-020** (dep lock), **F-022** (idempotency), **F-023** (refresh timing) — other PRs in the plan, deferred.
- HSTS preload list submission, CSP report-uri, subresource integrity — future hardening.
- Migrating CI/CD to scan Docker images (`trivy`, `grype`) — separate ops change.

## Capabilities

### New Capabilities
- `infra-hardening`: CORS lockdown, security headers, docs gating, container hardening, deployment-time env requirements, `.env` perms, HTTPS redirect.

### Modified Capabilities
- None. None of the four existing specs (`auth-security`, `error-normalization`, `input-validation`, `service-layer`) are touched; this change adds deployment-surface contracts that don't intersect their boundaries.

## Approach

- **F-005**: `origins` becomes a literal list — no env-conditional mutation. `allow_credentials=True` is kept (JWT in `Authorization` header works under the explicit origin list).
- **F-006**: `SecurityHeadersMiddleware.dispatch` mutates `response.headers` before returning. Headers are static dict; HSTS conditional on `settings.ENV`. Skip header injection for WebSocket upgrades (Starlette handles `Accept: text/event-stream` correctly out of the box).
- **F-011**: Build the `FastAPI(...)` kwargs conditionally: `docs_url=("/docs" if settings.ENV != "production" else None)`.
- **F-012**: Add `RUN adduser -D -g '' appuser` after `apk add`, `chown -R appuser:appuser /app`, then `USER appuser` before `CMD`. No multi-stage needed (single 27-line Dockerfile).
- **F-013**: New `.env` keys `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`, `REDIS_PASSWORD` (all `Optional` in `Settings` for backward compat with external Mongo Atlas). `docker-compose.yaml` references them via `${...}`. Remove `mongo_bebidas.ports` and `redis_bebidas.ports`.
- **F-016**: `ENV: str` (no default) — Pydantic raises on init. `main.py:274-275` simplified to `uvicorn.run(..., reload=False, host=("0.0.0.0" if dev else "127.0.0.1"))`. Tests inject `ENV=test` via conftest (already pattern).
- **F-021**: `Makefile` target `init-env: ; cp .env.example .env && chmod 600 .env`. `.env.example` adds a "Permissions" section.
- **F-025**: `from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware`; added after CORS, before exception handlers.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `main.py:65-66, 74-103, 274-275` | Modified | CORS, docs, ENV-conditional reload |
| `main.py` (new section) | New | `SecurityHeadersMiddleware` class + wiring (~25 lines) |
| `main.py` (new line) | New | `HTTPSRedirectMiddleware` add (1 line, conditional) |
| `config.py:45` | Modified | `ENV: str` (no default) — fail-fast |
| `Dockerfile:1-27` | Modified | `adduser`, `chown`, `USER appuser` |
| `docker-compose.yaml:22-41` | Modified | No host ports; env-var creds; pinned tags; Redis password |
| `.env.example` | Modified | New `MONGO_INITDB_ROOT_*`, `REDIS_PASSWORD`; `Permissions` section |
| `Makefile` (new) | New | `init-env` target |
| `README.md` | Modified | `chmod 600 .env` step |
| `tests/` | New | Header presence, CORS preflight, docs-gated, HTTPS-redirect, ENV fail-fast |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **400-line budget**: code ~80–120 + tests ~50 + docs ~30 = **~160–200** | Low | Single PR, well under budget. No chained PR needed. |
| CORS lockdown breaks existing frontend dev (custom port) | Med | Origins list already includes 3000/5173/8080/4200 + Vercel. Document custom-origin workflow in README. |
| `ENV` required breaks deployments that relied on default | Med | `.env.example` already documents `ENV=production`. Railway deploy sets it. CI sets `ENV=test`. |
| HTTPS redirect on dev breaks local testing | Low | Conditional on `ENV == "production"`; tests inject `ENV=test`. |
| `USER appuser` breaks `pip install` (read-only filesystem) | Low | `pip install` runs as root in `RUN` before `USER`; runtime layer is unprivileged. |
| Redis password mismatched between `Settings` and `docker-compose` | Low | Single `.env` source; tests for `REDIS_URL` consistency. |
| `.env` perms drift over time | Low | `Makefile init-env` target; CI lint: `stat -c '%a' .env == 600`. |
| Security headers break CORS preflight response | Low | Headers set on response, not on request; preflight still 200. |

## Rollback Plan

Revert the PR. No DB migration, no schema change, no token invalidation:

- CORS, docs, ENV, headers, HTTPS redirect are pure FastAPI startup wiring — revert restores previous behavior.
- Dockerfile non-root user is a build-time concern; revert restores the previous image layer.
- docker-compose revert restores exposed ports and `:latest` tags; existing local data volumes unaffected.
- `.env.example` revert restores the previous template; local `.env` unchanged.

## Dependencies

- None new. `starlette.middleware.httpsredirect.HTTPSRedirectMiddleware` is part of Starlette (already a FastAPI transitive dep).
- Existing: `pydantic_settings`, `fastapi==0.116`, Starlette.

## Success Criteria

- [ ] `origins` list contains no `*`; `allow_methods` exactly `["GET","POST","PUT","DELETE","PATCH","OPTIONS"]`; `allow_headers` exactly `["Authorization","Content-Type","X-Requested-With"]`
- [ ] Response to `GET /health` includes `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: ...`
- [ ] `GET /docs` and `GET /redoc` return 404 when `ENV=production`; 200 when `ENV=development`
- [ ] `ENV` unset at startup → Pydantic validation error, process exits non-zero
- [ ] `docker compose config` shows `mongo:7.0` and `redis:7.2-alpine` (no `:latest`); no host `ports:` on Mongo/Redis; Redis `command:` includes `--requirepass`
- [ ] `docker inspect` on built image: `User == "appuser"`
- [ ] `stat -c '%a' .env` returns `600` (or fresh `make init-env` produces it)
- [ ] `ENV=production` uvicorn binds `127.0.0.1:8000`; `HTTPSRedirectMiddleware` returns 307 to `https://...` for HTTP requests
- [ ] `pytest tests/ -v --tb=short` exits 0

## References

- `openspec/audits/security-audit-2026-06-15.md` (F-005, F-006, F-011, F-012, F-013, F-016, F-021, F-025; PR #4 of 6)
- Exemplar: `openspec/changes/archive/2026-07-27-input-validation/proposal.md`
- Previous PRs: `#1` (webhook+backdoor), `#2` (auth), `#3` (input-validation) — all merged
