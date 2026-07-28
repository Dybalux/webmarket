# Tasks: Infra Hardening — CORS, Headers, Docs, Docker, ENV, .env, HTTPS

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 160–200 (code ~80–120 + tests ~50 + docs ~30) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | auto-chain |
| Chain strategy | pending (not needed) |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Config, middleware, Docker, tests, docs — full change | PR 1 | `pytest tests/ -v --tb=short` | Local `uvicorn` + `docker compose up` | Revert single PR |

## Phase 1: Config — ENV Required, .env.example

- [x] 1.1 Modify `config.py`: change `ENV: str` to `ENV: str` (remove default `"development"`) so Pydantic fails fast if unset
- [x] 1.2 Add `MONGO_INITDB_ROOT_USERNAME: Optional[str] = None`, `MONGO_INITDB_ROOT_PASSWORD: Optional[str] = None`, `REDIS_PASSWORD: Optional[str] = None` to `Settings` in `config.py`
- [x] 1.3 Update `.env.example`: add `MONGO_INITDB_ROOT_USERNAME=`, `MONGO_INITDB_ROOT_PASSWORD=`, `REDIS_PASSWORD=`, and a `Permissions` section with `chmod 600 .env`

## Phase 2: Middleware — CORS Lockdown, Security Headers, HTTPS Redirect, Docs Gating

- [x] 2.1 Modify `main.py`: replace dynamic `origins` with literal list `["http://localhost:3000", "http://localhost:5173", "http://localhost:8080", "http://localhost:4200", "https://webmarket.vercel.app"]` plus `settings.FRONTEND_URL`; remove `*` branch
- [x] 2.2 Modify `main.py`: set `allow_methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"]` and `allow_headers=["Authorization","Content-Type","X-Requested-With"]` on `CORSMiddleware`
- [x] 2.3 Create `SecurityHeadersMiddleware` class in `main.py`: static `HEADERS` dict (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: geolocation=(), microphone=(), camera=()`); `dispatch` adds headers, adds `Strict-Transport-Security` when `ENV=production`
- [x] 2.4 Add `HTTPSRedirectMiddleware` in `main.py` when `ENV=production`; add `proxy_headers=True` to `uvicorn.run` for Cloudflare Tunnel
- [x] 2.5 Modify `main.py`: set `docs_url=None, redoc_url=None, openapi_url=None` when `ENV=production`
- [x] 2.6 Modify `main.py` uvicorn config: remove `reload` flag; bind to `127.0.0.1` in production, `0.0.0.0` otherwise

## Phase 3: Docker — Dockerfile Non-root, docker-compose Hardening

- [x] 3.1 Modify `Dockerfile`: add `RUN adduser -D -g '' appuser` after `apk add`, `RUN chown -R appuser:appuser /app`, add `USER appuser` before `CMD`
- [x] 3.2 Modify `docker-compose.yaml`: remove host `ports:` for `mongo_bebidas` and `redis_bebidas`; pin `mongo:7.0` and `redis:7.2-alpine`
- [x] 3.3 Modify `docker-compose.yaml`: replace hardcoded Mongo creds with `${MONGO_INITDB_ROOT_USERNAME}` and `${MONGO_INITDB_ROOT_PASSWORD}`; add `command: --requirepass ${REDIS_PASSWORD}` to Redis service
- [x] 3.4 Create `Makefile` with `init-env: cp .env.example .env && chmod 600 .env`
- [x] 3.5 Update `README.md`: add `chmod 600 .env` step in setup instructions

## Phase 4: Testing — Unit + Integration Tests

- [x] 4.1 Create `tests/test_infra_hardening.py`: unit test for `ENV` unset → `ValidationError` using `monkeypatch.delenv("ENV")` and `Settings(_env_file=None)`
- [x] 4.2 Integration test: `GET /health` returns security headers (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`)
- [x] 4.3 Integration test: `GET /docs` and `GET /redoc` return 404 when `ENV=production`; 200 when `ENV=development`
- [x] 4.4 Integration test: CORS preflight with `PUT` method and `Authorization` header returns allowed methods/headers exactly as specified
- [x] 4.5 Integration test: HTTP request to `ENV=production` app returns 307 redirect to `https://`
- [x] 4.6 Create `scripts/check_compose_hardening.sh`: shell script that runs `docker compose config` and greps for no host ports, pinned tags, `--requirepass`

## Phase 5: Cleanup — Verification

- [x] 5.1 Run `pytest tests/ -v --tb=short` and verify all new tests pass
- [x] 5.2 Run `docker compose config` and verify no host ports, pinned tags, Redis command
- [x] 5.3 Build Docker image and run `docker inspect` to verify `User == "appuser"`
- [x] 5.4 Verify `stat -c '%a' .env` returns `600` (or `make init-env` produces it)
- [x] 5.5 Manual smoke test: start app with `ENV=production`, verify `/docs` returns 404 and headers are present