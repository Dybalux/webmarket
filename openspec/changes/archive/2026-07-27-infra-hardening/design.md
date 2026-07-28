# Design: Infra Hardening — CORS, Headers, Docs, Docker, ENV, .env, HTTPS

## Technical Approach

Harden the deployment surface inside existing seams: module-level middleware wiring in `main.py` (same pattern as `MaintenanceModeMiddleware`), a required Pydantic field in `config.py`, an unprivileged `Dockerfile` layer, env-var credentials in `docker-compose.yaml`, docs/template updates. No new dependencies; `HTTPSRedirectMiddleware` ships with Starlette.

## Architecture Decisions

### Decision: Security headers mechanism

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Custom `SecurityHeadersMiddleware(BaseHTTPMiddleware)` in `main.py` | ~20 lines; matches existing `MaintenanceModeMiddleware` pattern | **Chosen** |
| Third-party (`secure`) | New dependency for a static dict | Rejected |
| Starlette built-in | Does not exist | N/A |

**Rationale**: Starlette ships no security-headers middleware; the codebase already owns this pattern. Headers are a static dict; `Strict-Transport-Security: max-age=31536000; includeSubDomains` only when `ENV == "production"`.

### Decision: HTTPS redirect

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `starlette.middleware.httpsredirect.HTTPSRedirectMiddleware` | Zero code, stdlib-grade, emits 307 | **Chosen** |
| Custom redirect middleware | Reimplements scheme check + URL swap for no gain | Rejected |

**Rationale**: Built-in does exactly what the spec requires; wired only when `ENV == "production"`. Uvicorn must honor `X-Forwarded-Proto` from Cloudflare: `uvicorn.run(..., proxy_headers=True)`, otherwise the middleware redirect-loops. (`forwarded_allow_ips` is a **uvicorn** setting, not Starlette — proposal phrasing corrected.)

### Decision: ENV enforcement

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `ENV: str` (no default) in `Settings` | Fail-fast at `Settings()` instantiation; Pydantic raises `ValidationError`, non-zero exit | **Chosen** |
| Startup check in lifespan | Runs after import; duplicates Pydantic; error appears later | Rejected |

**Rationale**: `config.py` already validates allowed values via `field_validator("ENV")`; dropping the default reuses that machinery. Tests inject `ENV=test`.

### Decision: Dockerfile structure

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Single-stage + `USER appuser` | 4 added lines; base already pinned (`python:3.13.7-alpine`) | **Chosen** |
| Multi-stage build | No compile step to justify it | Rejected |

**Rationale**: 27-line pure-Python Dockerfile. `pip install` runs as root in `RUN` before `USER`, so no permission breakage.

### Decision: Middleware order

Starlette wraps in reverse add-order (last added = outermost). Add both new middlewares **after** the existing adds:

    client → HTTPSRedirect → SecurityHeaders → Maintenance → CORS → router

**Rationale**: Redirect fires before any DB touch; headers land on every response including 503s and 307s.

## Data Flow

    HTTP request ──→ HTTPSRedirectMiddleware (prod only, 307 if http)
                  ──→ SecurityHeadersMiddleware (adds 4 headers + HSTS in prod)
                  ──→ MaintenanceModeMiddleware (existing)
                  ──→ CORSMiddleware (locked methods/headers, explicit origins)
                  ──→ router

    Startup: Settings() → ENV missing? → ValidationError, exit ≠ 0
             ENV=production? → docs_url=None, redoc_url=None, openapi_url=None
                               bind 127.0.0.1, reload=False, proxy_headers=True

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `main.py` | Modify | Literal `origins` (drop `*` branch); locked methods/headers; conditional `docs_url`/`redoc_url`/`openapi_url`; `SecurityHeadersMiddleware` add; conditional `HTTPSRedirectMiddleware` add; single `uvicorn.run` with `proxy_headers=True`, host by ENV |
| `config.py` | Modify | `ENV: str` required (line 45); add `MONGO_INITDB_ROOT_USERNAME/PASSWORD`, `REDIS_PASSWORD` as `Optional` |
| `Dockerfile` | Modify | `adduser`, `chown`, `USER appuser` before `CMD` |
| `docker-compose.yaml` | Modify | Remove DB `ports:`; `mongo:7.0`, `redis:7.2-alpine`; creds via `${...}`; `command: --requirepass ${REDIS_PASSWORD}` |
| `example.env` | Modify | Add `MONGO_INITDB_ROOT_*`, `REDIS_PASSWORD`, Permissions section (`chmod 600`) |
| `Makefile` | Create | `init-env: cp example.env .env && chmod 600 .env` |
| `README.md` | Modify | `chmod 600 .env` setup step |
| `tests/test_infra_hardening.py` | Create | Header presence, CORS preflight, docs gating, HTTPS redirect, ENV fail-fast |
| `scripts/check_compose_hardening.sh` | Create | `docker compose config` greps: no host ports, pinned tags, `--requirepass` |

## Interfaces / Contracts

```python
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    HEADERS = {
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.update(self.HEADERS)
        if settings.ENV == "production":
            response.headers["Strict-Transport-Security"] = \
                "max-age=31536000; includeSubDomains"
        return response
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `ENV` unset → `ValidationError` | `Settings(_env_file=None)` with `monkeypatch.delenv("ENV")` |
| Integration | Headers on `/health`; docs 404/200; CORS preflight allow-lists; 307 in prod | `monkeypatch.setenv` + `importlib.reload(config)` + `importlib.reload(main)`, then `httpx.ASGITransport(main.app)`. conftest's `test_app` deliberately bypasses `main.py`, so these tests hit the real app. |
| Integration (shell) | Compose pins, no host ports, Redis auth; image `User=appuser` | `scripts/check_compose_hardening.sh` in CI; `docker inspect` |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration. Operators must set `ENV` before deploy (Railway sets `ENV=production`; CI sets `ENV=test`). Fresh clones use `make init-env`.

## Open Questions

- [ ] Does Railway's healthcheck hit `/health` over plain HTTP? If so, `HTTPSRedirectMiddleware` 307s it — confirm it goes through Cloudflare or relies on redirect-following.
- [ ] Keep `openapi_url` exposed in `test` env (current plan: yes — only `production` gates docs).
