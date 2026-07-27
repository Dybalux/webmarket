# Webmarket Security Audit — 2026-06-15

## Executive Summary

- **Overall posture**: **HIGH-RISK**
- **Total findings**: 26 (CRITICAL: 3, HIGH: 8, MEDIUM: 9, LOW: 6, INFO: 3)
- **Top 3 things to fix immediately**:
  1. **Webhook signature validation is non-blocking** — attackers can forge payment notifications and manipulate order/payment state.
  2. **Monetary values use `float` instead of `Decimal`** — precision loss, rounding errors, and potential financial imbalance.
  3. **Dead-code backdoor with hardcoded admin credentials** in `security.py` — easily re-activated by accident.

## Methodology

- **Files reviewed**: 35+ source files including all routers, services, models, security, config, database, email service, stock helpers, audit logger, Dockerfile, docker-compose, requirements files, and deployment docs.
- **Tools run**: None installed. `bandit`, `pip-audit`, and `semgrep` were not available in the environment. Manual review was performed for all OWASP categories and dependency analysis.
- **Manual review depth**: Full read of every Python file in `routers/`, `services/`, `models.py`, `security.py`, `config.py`, `database.py`, `email_service.py`, `stock_helpers.py`, `audit_logger.py`, `main.py`, `utils/errors.py`, and infrastructure files.
- **Out-of-scope**: Runtime penetration testing, infrastructure-as-code beyond Docker, Cloudflare dashboard audit, mobile app audit, third-party MercadoPago API pentest.

## Findings

### F-001 — Webhook signature validation is non-blocking (warns only)
- **Severity**: CRITICAL
- **OWASP**: A08 — Integrity Failures
- **CWE**: CWE-345 (Insufficient Verification of Data Authenticity)
- **Location**: `services/payments.py:189-222`
- **Description**: The `_validate_signature` function verifies the HMAC-SHA256 signature of MercadoPago webhooks but is documented as "Non-blocking (warns only)". When the signature is missing, malformed, or invalid, it logs a warning and returns without raising an exception. The caller (`process_webhook`) continues processing the webhook, allowing an attacker to forge payment notifications and transition orders to `PROCESSING` or `CANCELLED` without possessing the webhook secret.
- **Evidence**:
  ```python
  def _validate_signature(...) -> None:
      """HMAC-SHA256 webhook signature check. Non-blocking (warns only)."""
      ...
      if not hmac.compare_digest(rh, expected):
          logger.warning("Invalid webhook signature for id=%s.", payment_id)
      else:
          logger.info("Signature OK for id=%s.", payment_id)
  ```
- **Impact**: An attacker can create fake payment webhooks, mark orders as paid, and potentially trigger stock depletion or financial loss.
- **Recommended Fix**: Change `_validate_signature` to raise `ForbiddenError` or `HTTPException(403)` when the signature is invalid. Require signature validation in production (`ENV=production`). If `MERCADOPAGO_WEBHOOK_SECRET` is not configured, reject the webhook in production.
- **References**: OWASP A08, MercadoPago Webhooks docs

### F-002 — Monetary values use `float` instead of `Decimal`
- **Severity**: CRITICAL
- **OWASP**: A04 — Insecure Design
- **CWE**: CWE-681 (Incorrect Conversion between Numeric Types)
- **Location**: `models.py` (passim), `services/orders.py`, `services/pricing.py`, `services/payments.py`
- **Description**: All price and amount fields (`price`, `total_amount`, `shipping_cost`, `amount`) are defined as `float` in Pydantic models and used throughout business logic. Python `float` (IEEE 754 double precision) cannot exactly represent many decimal fractions, leading to rounding errors in financial calculations. This can cause invoice totals to mismatch, tax calculations to be incorrect, and database aggregations to drift.
- **Evidence**:
  ```python
  # models.py:87
  price: float = Field(..., gt=0, description="Precio de venta (mayor que cero)")
  # models.py:281
  total_amount: float = Field(..., ge=0)
  # services/pricing.py:50
  adjusted_price = base_price * settings.multiplier
  return round(adjusted_price, 2)
  ```
- **Impact**: Financial imbalance, incorrect revenue reports, potential legal/compliance issues in Argentina (AFIP).
- **Recommended Fix**: Replace all monetary `float` fields with `decimal.Decimal` at the Pydantic model level. Use `Decimal` for all arithmetic in services. Configure MongoDB to store `Decimal128` (via `bson.Decimal128`) or store as string/integer cents.
- **References**: OWASP A04, CWE-681, Python `decimal` module docs

### F-003 — Dead-code backdoor with hardcoded admin credentials
- **Severity**: CRITICAL
- **OWASP**: A07 — Auth Failures
- **CWE**: CWE-798 (Use of Hard-coded Credentials)
- **Location**: `security.py:148-175`
- **Description**: The `authenticate_user` function contains a hardcoded fake user database with an admin account (`admin@example.com` / `123456`). Although this function appears to be dead code (not imported by any router), it remains in the codebase and could be accidentally wired back into an endpoint by a future developer or refactor. It also serves as a dangerous example of what "simulation" looks like.
- **Evidence**:
  ```python
  def authenticate_user(user: UserLogin) -> dict:
      fake_user_db = {
          "admin@example.com": {
              "user_id": "123",
              "hashed_password": get_password_hash("123456"),
              "roles": ["admin"],
              "age_verified": True
          }
      }
      ...
  ```
- **Impact**: If accidentally re-introduced to an endpoint, it provides an instant admin bypass.
- **Recommended Fix**: Remove the `authenticate_user` function entirely. If a mock is needed for tests, place it in `tests/` and use `pytest` fixtures.
- **References**: OWASP A07, CWE-798

### F-004 — python-jose is unmaintained and has known vulnerabilities
- **Severity**: HIGH
- **OWASP**: A06 — Vulnerable Components
- **CWE**: CWE-1104 (Use of Unmaintained Third-Party Components)
- **Location**: `requirements.txt:28`, `security.py:3`
- **Description**: The project uses `python-jose==3.5.0` for JWT signing and verification. `python-jose` is effectively unmaintained (last release 2023) and has known security issues (e.g., CVE-2024-23342, algorithm confusion with `none`, weak key handling). The `jose` library is widely discouraged in favor of `PyJWT` or `authlib`.
- **Evidence**:
  ```python
  from jose import JWTError, jwt
  ```
  ```
  python-jose==3.5.0
  ```
- **Impact**: Potential algorithm confusion attacks, key confusion, or future CVEs that will not be patched.
- **Recommended Fix**: Replace `python-jose` with `PyJWT>=2.8.0` or `authlib`. Update `decode_access_token` and `create_access_token` accordingly. Ensure `algorithms` parameter is explicitly set and does not include `none`.
- **References**: CVE-2024-23342, PyJWT docs, Authlib docs

### F-005 — CORS allows all methods and headers; origins include `*` in development
- **Severity**: HIGH
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-942 (Overly Permissive Cross-domain Whitelist)
- **Location**: `main.py:74-103`
- **Description**: The CORS middleware is configured with `allow_methods=["*"]` and `allow_headers=["*"]` unconditionally. In development mode (`ENV=development`, which is the default), `*` is appended to `origins`, allowing any origin. While production strips the wildcard, the `allow_methods` and `allow_headers` remain overly permissive. Additionally, `FRONTEND_URL` is read from settings and added to origins without validation.
- **Evidence**:
  ```python
  if settings.ENV.lower() == "development":
      origins.append("*")
  ...
  app.add_middleware(
      CORSMiddleware,
      allow_origins=origins,
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- **Impact**: In development, any malicious website can make authenticated requests to the API using the user's cookies/credentials. In production, overly permissive methods/headers increase attack surface.
- **Recommended Fix**: Remove `*` from origins even in development. Use an explicit list of allowed origins. Restrict `allow_methods` to `GET, POST, PUT, DELETE, PATCH, OPTIONS`. Restrict `allow_headers` to `Authorization, Content-Type, X-Requested-With`.
- **References**: OWASP A05, FastAPI CORS docs

### F-006 — No HTTP security headers (CSP, HSTS, X-Frame-Options, etc.)
- **Severity**: HIGH
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-693 (Protection Mechanism Failure)
- **Location**: `main.py` (missing middleware)
- **Description**: There is no middleware or configuration setting Content-Security-Policy, Strict-Transport-Security, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, or Permissions-Policy. The API is exposed to clickjacking, MIME-sniffing attacks, and lacks TLS enforcement signals.
- **Evidence**: No `SecurityHeadersMiddleware` or `HTTPSRedirectMiddleware` imported or added.
- **Impact**: Clickjacking of admin panels, MIME sniffing leading to XSS, lack of TLS downgrade protection.
- **Recommended Fix**: Add a custom middleware or use `starlette.middleware.trustedhost` + `Secure` cookie flags. Set headers:
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), microphone=()`
  - `Strict-Transport-Security: max-age=63072000; includeSubDomains` (when behind TLS)
- **References**: OWASP Secure Headers Project, MDN HTTP headers

### F-007 — Missing rate limiting on sensitive endpoints
- **Severity**: HIGH
- **OWASP**: A04 — Insecure Design
- **CWE**: CWE-770 (Allocation of Resources Without Limits or Throttling)
- **Location**: `routers/auth.py:90`, `routers/payments.py:36`, `routers/orders.py:43`, `routers/cart.py:50`, `routers/admin.py` (passim)
- **Description**: Only `/auth/token` has rate limiting (5 requests / 60 seconds). All other endpoints including registration, passwordless operations, order creation, payment preference creation, cart operations, and admin endpoints have no rate limiting. The webhook endpoint (`/payments/webhook`) is particularly vulnerable to DDoS or brute-force replay attacks.
- **Evidence**:
  ```python
  @router.post("/register", status_code=status.HTTP_201_CREATED)  # NO rate limit
  @router.post("/webhook")  # NO rate limit
  @router.post("/")  # create_order — NO rate limit
  ```
- **Impact**: Brute-force registration spam, credential stuffing via registration, webhook DDoS, order creation spam, cart manipulation.
- **Recommended Fix**: Apply `RateLimiter` to all write endpoints. Use stricter limits for auth endpoints (register, refresh). Use IP-based or user-based throttling for webhooks. Consider `slowapi` or `fastapi-limiter` with Redis backend.
- **References**: OWASP A04, OWASP Rate Limiting Cheat Sheet

### F-008 — NoSQL injection / ReDoS via `$regex` in admin and product endpoints
- **Severity**: HIGH
- **OWASP**: A03 — Injection
- **CWE**: CWE-943 (Improper Neutralization of Special Elements in Data Query Logic)
- **Location**: `routers/admin.py:136-139`, `routers/products.py:110-114`
- **Description**: User-provided `search` strings are passed directly into MongoDB `$regex` queries without sanitization. An attacker can provide a regex with catastrophic backtracking (ReDoS) or use regex operators to exfiltrate data. The `sort_by` parameter in admin endpoints is also passed directly to `sort()` without a whitelist, allowing field injection.
- **Evidence**:
  ```python
  # admin.py:136-139
  query["$or"] = [
      {"username": {"$regex": search, "$options": "i"}},
      {"email": {"$regex": search, "$options": "i"}}
  ]
  # products.py:110-114
  query["$or"] = [
      {"name": {"$regex": search, "$options": "i"}},
      {"description": {"$regex": search, "$options": "i"}}
  ]
  ```
- **Impact**: ReDoS causing CPU exhaustion on MongoDB. Potential data exfiltration if regex is used in a more complex query.
- **Recommended Fix**: Sanitize `search` by escaping regex special characters (`.*+?^${}()|[]\`). For `sort_by`, maintain a strict whitelist of allowed fields. Prefer `$text` search over `$regex` for performance and safety.
- **References**: OWASP A03, MongoDB `$regex` docs, ReDoS OWASP Cheat Sheet

### F-009 — Weak password policy (minimum 8 chars, no complexity)
- **Severity**: HIGH
- **OWASP**: A07 — Auth Failures
- **CWE**: CWE-521 (Weak Password Requirements)
- **Location**: `models.py:133`
- **Description**: The `UserRegister` model enforces only a minimum length of 8 characters for passwords. There is no requirement for uppercase, lowercase, digits, or special characters. This allows passwords like `password`, `12345678`, or `aaaaaaaa`.
- **Evidence**:
  ```python
  password: str = Field(..., min_length=8, description="Contraseña segura (mínimo 8 caracteres)")
  ```
- **Impact**: Users will choose weak passwords, making accounts susceptible to brute-force and credential stuffing.
- **Recommended Fix**: Add a Pydantic validator for password complexity (e.g., at least 1 uppercase, 1 lowercase, 1 digit, 1 special character). Consider integrating `zxcvbn` or a similar strength checker. Reject common passwords against a dictionary.
- **References**: OWASP A07, NIST SP 800-63B password guidelines

### F-010 — Admin `sort_by` field injection
- **Severity**: HIGH
- **OWASP**: A03 — Injection
- **CWE**: CWE-943 (Improper Neutralization of Special Elements in Data Query Logic)
- **Location**: `routers/admin.py:151`, `routers/admin.py:217`
- **Description**: The `sort_by` query parameter in `get_admin_users` and `get_admin_orders` is passed directly to `collection.find(...).sort(sort_by, sort_order)`. There is no whitelist of allowed fields. An attacker can sort by `hashed_password` (to potentially leak timing information) or by arbitrary injected fields.
- **Evidence**:
  ```python
  users_cursor = users_collection.find(query).sort(sort_by, sort_order).skip(skip).limit(limit)
  orders_cursor = orders_collection.find(query).sort(sort_by, sort_order).skip(skip).limit(limit)
  ```
- **Impact**: Information leakage via timing, potential DoS if sorting on unindexed fields, or injection of arbitrary sort keys.
- **Recommended Fix**: Whitelist allowed `sort_by` fields to `created_at`, `username`, `email`, `role`, `updated_at`. Reject unknown fields with `HTTPException(400)`.
- **References**: OWASP A03, MongoDB sort injection

### F-011 — Swagger/ReDoc docs exposed in production
- **Severity**: MEDIUM
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-200 (Exposure of Sensitive Information to an Unauthorized Actor)
- **Location**: `main.py:65-66`
- **Description**: `docs_url="/docs"` and `redoc_url="/redoc"` are enabled unconditionally. In production, this exposes the full API schema, model names, and endpoint structure to unauthenticated attackers, reducing the effort needed for reconnaissance.
- **Evidence**:
  ```python
  app = FastAPI(
      ...
      docs_url="/docs",
      redoc_url="/redoc",
      ...
  )
  ```
- **Impact**: API reconnaissance, easier targeting of endpoints.
- **Recommended Fix**: Set `docs_url=None` and `redoc_url=None` when `settings.ENV == "production"`. Alternatively, gate them behind admin authentication.
- **References**: OWASP A05, FastAPI docs

### F-012 — Dockerfile runs as root; no non-root user
- **Severity**: MEDIUM
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-250 (Execution with Unnecessary Privileges)
- **Location**: `Dockerfile:1-27`
- **Description**: The Dockerfile uses `python:3.13.7-alpine` (note: project claims Python 3.14.5, but Dockerfile is stale) and does not create a non-root user. The container runs as root, increasing the blast radius if the application is compromised. Additionally, the base image is not the latest patch version.
- **Evidence**:
  ```dockerfile
  FROM python:3.13.7-alpine
  ...
  # No USER directive
  CMD ["python3", "main.py"]
  ```
- **Impact**: Container escape, privilege escalation, broader filesystem access if RCE is achieved.
- **Recommended Fix**: Add `RUN adduser -D appuser && chown -R appuser /app` and `USER appuser`. Update base image to `python:3.14.5-alpine` or pin to a specific digest. Consider multi-stage build to reduce image size and attack surface.
- **References**: OWASP A05, Docker Security Best Practices

### F-013 — docker-compose exposes MongoDB and Redis with weak credentials
- **Severity**: MEDIUM
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-522 (Insufficiently Protected Credentials)
- **Location**: `docker-compose.yaml:22-41`
- **Description**: MongoDB and Redis services are exposed on host ports `27017` and `6379`. MongoDB uses a hardcoded root password (`miContraseñaSecreta`). Redis has no password. In a shared environment (e.g., CI, shared dev server), this exposes the database to lateral movement. Images use `mongo:latest` and `redis:latest` without version pinning.
- **Evidence**:
  ```yaml
  mongo_bebidas:
    image: mongo:latest
    ports:
      - "27017:27017"
    environment:
      - MONGO_INITDB_ROOT_USERNAME=admin
      - MONGO_INITDB_ROOT_PASSWORD=miContraseñaSecreta
  redis_bebidas:
    image: redis:latest
    ports:
      - "6379:6379"
  ```
- **Impact**: Unauthorized DB access, data exfiltration, cache poisoning, potential RCE via Redis.
- **Recommended Fix**: Remove `ports` for MongoDB and Redis (use Docker network only). Use `.env` for credentials, not hardcoded strings. Pin image versions (`mongo:7.0`, `redis:7.2`). Add Redis `requirepass`.
- **References**: OWASP A05, Docker Compose security best practices

### F-014 — Missing audit logging for critical security events
- **Severity**: MEDIUM
- **OWASP**: A09 — Logging Failures
- **CWE**: CWE-778 (Insufficient Logging)
- **Location**: `audit_logger.py` (incomplete coverage), `routers/` (passim)
- **Description**: The `audit_logger.py` only defines 6 event types. Critical security events are missing: failed password attempts (not logged via audit), admin role changes (not logged via audit), stock modifications (not logged via audit), payment failures (not logged via audit), CORS preflight abuse, and webhook signature failures. Auth endpoints use `logging.getLogger(__name__)` instead of `audit_logger.log_audit`.
- **Evidence**:
  ```python
  class AuditEvent(str, Enum):
      USER_LOGIN_SUCCESS = "USER_LOGIN_SUCCESS"
      USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
      ...
  ```
  ```python
  # auth.py:131 — uses plain logger, not audit
  logger.info(f"Usuario {user['username']} ha iniciado sesión...")
  ```
- **Impact**: Delayed incident detection, inability to reconstruct attack timelines, compliance gaps.
- **Recommended Fix**: Expand `AuditEvent` to cover all security-relevant actions. Ensure every auth, admin, payment, and stock mutation is logged via `audit_logger.log_audit`. Consider shipping audit logs to a SIEM or immutable store.
- **References**: OWASP A09, OWASP Logging Cheat Sheet

### F-015 — No password reset or email verification flow
- **Severity**: MEDIUM
- **OWASP**: A07 — Auth Failures
- **CWE**: CWE-640 (Weak Password Recovery Mechanism)
- **Location**: `routers/auth.py` (missing endpoints)
- **Description**: The authentication system lacks password reset, forgot-password, and email verification endpoints. Users who forget their password cannot recover their account. New registrations are not verified, allowing anyone to register with any email address.
- **Impact**: Account lockout, spam registrations, inability to enforce email ownership.
- **Recommended Fix**: Implement `/auth/forgot-password` and `/auth/reset-password` with time-limited, single-use tokens sent via email. Implement `/auth/verify-email` with a token sent after registration. Use `audit_logger` for these events.
- **References**: OWASP A07, NIST SP 800-63B

### F-016 — Default environment is `development` with debug features enabled
- **Severity**: MEDIUM
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-489 (Active Debug Code)
- **Location**: `config.py:39`, `main.py:274-275`
- **Description**: `ENV` defaults to `development`. In development, `uvicorn.run(..., reload=True)` is enabled, which watches the filesystem and auto-reloads. If deployed without explicitly setting `ENV=production`, the application will expose debug behavior and auto-reload.
- **Evidence**:
  ```python
  ENV: str = "development"
  ...
  if(settings.ENV.lower() == "development"):
      uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
  ```
- **Impact**: If `ENV` is accidentally left as default in production, auto-reload exposes file-watching capabilities and debug mode.
- **Recommended Fix**: Make `ENV` a required setting with no default. Fail fast at startup if `ENV` is not set. Alternatively, default to `production` and require explicit `development` for local work.
- **References**: OWASP A05, FastAPI deployment docs

### F-017 — No account lockout after failed login attempts
- **Severity**: MEDIUM
- **OWASP**: A07 — Auth Failures
- **CWE**: CWE-307 (Improper Restriction of Excessive Authentication Attempts)
- **Location**: `routers/auth.py:120-136`
- **Description**: The login endpoint has rate limiting (5/min), but there is no account-level lockout. A distributed attacker can cycle through IPs or simply stay below the rate limit and attempt thousands of passwords per day against a single account.
- **Impact**: Brute-force and credential stuffing against specific accounts.
- **Recommended Fix**: Implement progressive delays or temporary lockouts after N consecutive failed attempts for a specific username. Store failed attempt counters in Redis with TTL.
- **References**: OWASP A07, OWASP Brute Force Cheat Sheet

### F-018 — HTML injection in email notification template
- **Severity**: MEDIUM
- **OWASP**: A03 — Injection
- **CWE**: CWE-79 (Improper Neutralization of Input During Web Page Generation)
- **Location**: `email_service.py:54-102`
- **Description**: The `email_service.py` builds an HTML email using f-strings with values from the database (`user_email`, `order_id`, `total_amount`, `payment_method`). If a user manages to inject malicious data into these fields (e.g., via email registration or order creation), the resulting email may contain XSS or HTML injection payloads. While most email clients do not execute JavaScript, HTML injection can still be used for phishing or UI manipulation.
- **Evidence**:
  ```python
  html_content = f"""
  ...
  <td style="...">{user_email}</td>
  ...
  <td style="...">{payment_method}</td>
  """
  ```
- **Impact**: HTML injection in admin emails, potential phishing vectors.
- **Recommended Fix**: Use an HTML templating engine (Jinja2) with auto-escaping. If f-strings are used, manually escape all interpolated values with `html.escape()`.
- **References**: OWASP A03, CWE-79

### F-019 — Stale deployment documentation (`openspec/config.yaml` says Railway)
- **Severity**: LOW
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-1104 (Use of Unmaintained Third-Party Components)
- **Location**: `openspec/config.yaml:11`
- **Description**: The `openspec/config.yaml` explicitly states "Deployment: Railway (Dockerfile)". The project migrated away from Railway on 2026-06-13. Stale documentation can mislead operators, CI pipelines, or future developers into deploying to the wrong platform or using outdated infrastructure assumptions.
- **Evidence**:
  ```yaml
  Deployment: Railway (Dockerfile), Python 3.13-alpine, gunicorn for prod.
  ```
- **Impact**: Operational confusion, potential accidental deployment to wrong platform.
- **Recommended Fix**: Update `openspec/config.yaml` to reflect the current deployment target (Cloudflare Tunnel + Docker/Vercel). Add a version/date field.
- **References**: OWASP A05

### F-020 — Dependency version mismatches between `requirements.txt` and project context
- **Severity**: LOW
- **OWASP**: A06 — Vulnerable Components
- **CWE**: CWE-1104 (Use of Unmaintained Third-Party Components)
- **Location**: `requirements.txt` (passim)
- **Description**: The `requirements.txt` versions do not match the versions stated in the project context. For example: `fastapi==0.116.1` vs claimed `0.136.3`; `redis==6.4.0` vs claimed `8.0.0`; `mercadopago==2.3.0` vs claimed `3.2.0`; `pydantic==2.11.7` vs claimed `2.13.4`; `resend==2.5.1` vs claimed `2.30.1`. This makes it unclear which versions are actually deployed and whether known CVEs apply.
- **Impact**: Inability to accurately assess vulnerability exposure. Potential runtime errors if code uses features from newer versions.
- **Recommended Fix**: Run `pip freeze > requirements.txt` from the active environment. Maintain a `requirements.lock` or `poetry.lock` file. Update `requirements.txt` to match actual deployment versions.
- **References**: OWASP A06, pip-audit docs

### F-021 — `.env` file exists with 644 permissions
- **Severity**: LOW
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-732 (Incorrect Permission Assignment for Critical Resource)
- **Location**: `/home/dybalux/Escritorio_Dev/webmarket/.env`
- **Description**: The `.env` file exists on disk with permissions `644` (world-readable). Any user on the system can read the JWT secret key, database URL, and API keys. While `.env` is in `.gitignore`, filesystem permissions are too permissive.
- **Evidence**: `ls -la .env` → `-rw-r--r-- 1 dybalux dybalux 644 jun 11 01:20 .env`
- **Impact**: Local privilege escalation, secret exfiltration by other users or compromised services.
- **Recommended Fix**: `chmod 600 .env`. Document this in `.env.example`. Consider using a secrets manager (e.g., Docker secrets, AWS Secrets Manager, HashiCorp Vault) for production.
- **References**: OWASP A05, Linux file permissions

### F-022 — Missing idempotency key on `create_mp_preference` and order creation
- **Severity**: LOW
- **OWASP**: A04 — Insecure Design
- **CWE**: CWE-362 (Race Condition)
- **Location**: `services/payments.py:51`, `services/orders.py:47`
- **Description**: The `create_mp_preference` endpoint does not use an idempotency key when calling MercadoPago. If a user double-clicks or retries the request, multiple preferences may be created. Similarly, order creation lacks an idempotency key, which could lead to duplicate orders if the client retries.
- **Impact**: Duplicate payment preferences, duplicate orders, inventory inconsistencies.
- **Recommended Fix**: Accept an `Idempotency-Key` header from the client. Store processed keys in Redis for 24h. Reject duplicate requests with the same key. Pass `Idempotency-Key` to MercadoPago API calls.
- **References**: OWASP A04, MercadoPago Idempotency docs

### F-023 — Refresh token verification vulnerable to timing attacks
- **Severity**: LOW
- **OWASP**: A02 — Cryptographic Failures
- **CWE**: CWE-208 (Observable Timing Discrepancy)
- **Location**: `routers/auth.py:193-202`
- **Description**: The refresh token endpoint iterates over all valid refresh tokens in the database and calls `verify_refresh_token` (bcrypt) for each. An attacker can measure the response time to determine if a token exists (timing attack). Additionally, the `limit(50)` means if there are more than 50 valid tokens, some may be missed.
- **Evidence**:
  ```python
  cursor = refresh_tokens_collection.find({
      "revoked": False,
      "expires_at": {"$gt": now}
  }).limit(50)
  valid_token_doc = None
  async for token_doc in cursor:
      if verify_refresh_token(refresh_token, token_doc["token"]):
          valid_token_doc = token_doc
          break
  ```
- **Impact**: Information leakage about token existence. Potential bypass if token is beyond the 50-token limit.
- **Recommended Fix**: Store a hash prefix or lookup key (e.g., SHA-256 of the token) alongside the bcrypt hash to allow direct indexed lookup. Use `secrets.compare_digest` for comparison (already done via `verify_refresh_token`). Remove the 50-token limit.
- **References**: OWASP A02, CWE-208

### F-024 — No two-factor authentication (2FA)
- **Severity**: INFO
- **OWASP**: A07 — Auth Failures
- **CWE**: CWE-308 (Use of Single-factor Authentication)
- **Location**: `routers/auth.py` (missing)
- **Description**: The system supports only username/password + JWT. There is no support for TOTP, SMS, or WebAuthn 2FA. For an e-commerce platform handling alcohol sales and payments, this is a notable gap.
- **Impact**: Compromised credentials grant full account access.
- **Recommended Fix**: Consider TOTP (e.g., `pyotp`) for admin accounts as a first step. Evaluate WebAuthn for high-value users.
- **References**: OWASP A07, NIST SP 800-63B

### F-025 — No HTTPS redirect middleware
- **Severity**: INFO
- **OWASP**: A05 — Security Misconfiguration
- **CWE**: CWE-319 (Cleartext Transmission of Sensitive Information)
- **Location**: `main.py` (missing)
- **Description**: The application does not enforce HTTPS at the application layer. It relies entirely on Cloudflare Tunnel for TLS termination. If the tunnel is bypassed or the backend is accessed directly (e.g., via Docker network, internal IP), traffic is in cleartext.
- **Impact**: Cleartext exposure of JWTs, passwords, and payment data if direct access is possible.
- **Recommended Fix**: Add `HTTPSRedirectMiddleware` from `starlette.middleware.httpsredirect` when `ENV=production`. Ensure `X-Forwarded-Proto` header is trusted. Bind uvicorn to `127.0.0.1` instead of `0.0.0.0` when behind a tunnel.
- **References**: OWASP A05, FastAPI HTTPS docs

### F-026 — Missing `extra="forbid"` on Pydantic models; `config.py` uses `extra="allow"`
- **Severity**: INFO
- **OWASP**: A03 — Injection
- **CWE**: CWE-20 (Improper Input Validation)
- **Location**: `config.py:50`, `models.py` (passim)
- **Description**: `Settings` in `config.py` uses `extra="allow"`, which silently accepts and stores unexpected fields. Many Pydantic models do not explicitly set `extra="forbid"`, meaning extra fields in JSON payloads are silently ignored rather than rejected. This can mask typos or injection attempts.
- **Evidence**:
  ```python
  model_config = SettingsConfigDict(
      env_file=".env",
      extra="allow"
  )
  ```
- **Impact**: Silent acceptance of unexpected data, potential confusion, or data leakage if extra fields are persisted to MongoDB.
- **Recommended Fix**: Use `extra="forbid"` on all request models. Use `extra="ignore"` only on internal models where necessary. For `Settings`, consider `extra="ignore"` if you want to be lenient with env vars, but log warnings.
- **References**: OWASP A03, Pydantic docs

## Dependency Audit (pip-audit output summary)

- **Tool**: pip-audit (not installed, manual review)
- **Vulnerable packages** (based on version review and known CVEs):
  - `python-jose==3.5.0` — unmaintained, known algorithm confusion issues (CVE-2024-23342). **Replace ASAP.**
  - `fastapi==0.116.1` — may be outdated vs claimed `0.136.3`. Review for CVEs applicable to 0.116.1.
  - `mercadopago==2.3.0` — may be outdated vs claimed `3.2.0`. Review MP SDK changelog for security fixes.
  - `redis==6.4.0` — may be outdated vs claimed `8.0.0`. Review Redis-py changelog.
  - `pydantic==2.11.7` — may be outdated vs claimed `2.13.4`. Review for security fixes.
  - `resend==2.5.1` — may be outdated vs claimed `2.30.1`. Review for API/security fixes.

*Note: Without pip-audit installed, exact CVE mappings cannot be verified automatically. Install `pip-audit` and run `pip-audit -r requirements.txt` for a definitive report.*

## Static Analysis Summary (Bandit output summary)

- **Tool**: Bandit (not installed, manual review)
- **Findings** (manual equivalents):
  - **B102**: `exec` / `eval` — **Not found** in codebase.
  - **B105**: Hardcoded password — Found in `security.py` (`123456` in `authenticate_user`).
  - **B106**: Hardcoded password function argument — Not found.
  - **B301**: `pickle` — Not found.
  - **B307**: `eval` — Not found.
  - **B608**: Hardcoded SQL expressions — Not applicable (MongoDB).
  - **B105 / B106**: `MONGO_INITDB_ROOT_PASSWORD=miContraseñaSecreta` in `docker-compose.yaml`.
  - **B108**: Hardcoded tmp directory — Not found.
  - **B602**: `subprocess` with shell=True — Not found.
  - **B603**: `subprocess` without shell — Not found.

*Note: Without Bandit installed, a full automated scan could not be performed. Install `bandit` and run `bandit -r . -f json` for a definitive report.*

## Coverage Matrix

| OWASP | Reviewed | Findings | Notes |
|-------|----------|----------|-------|
| A01 Broken Access Control | yes | F-003, F-010, F-011 | Missing RBAC on some endpoints; dead backdoor |
| A02 Cryptographic Failures | yes | F-004, F-023 | python-jose unmaintained; refresh timing attack |
| A03 Injection | yes | F-008, F-018, F-026 | NoSQL/ReDoS via regex; HTML injection; extra fields |
| A04 Insecure Design | yes | F-002, F-007, F-022 | Float for money; missing rate limits; no idempotency |
| A05 Security Misconfiguration | yes | F-005, F-006, F-011, F-012, F-013, F-016, F-019, F-021, F-025 | CORS, missing headers, docs, Docker, stale docs, .env perms |
| A06 Vulnerable Components | yes | F-004, F-020 | python-jose, version mismatches |
| A07 Auth Failures | yes | F-003, F-009, F-015, F-017, F-024 | Weak passwords, no reset, no lockout, dead backdoor |
| A08 Integrity Failures | yes | F-001 | Webhook signature non-blocking |
| A09 Logging Failures | yes | F-014 | Missing audit coverage |
| A10 SSRF | yes | — | No user-controlled URL fetching found; Resend URLs are hardcoded |

## Out-of-Scope / Not Reviewed

- Runtime penetration testing (e.g., live fuzzing, authenticated API testing).
- Infrastructure-as-code beyond Docker (e.g., Kubernetes manifests, Terraform).
- Cloudflare dashboard configuration (e.g., WAF rules, access policies, mTLS settings).
- MercadoPago API security beyond webhook signature validation.
- Mobile app security (if a mobile client exists).
- Physical security of the host running the Docker containers.
- Network segmentation between services (Docker network is `default`).
- Backup encryption and retention policies.
- Third-party Vercel security configuration.

## Recommended Next Steps

1. **CRITICAL — Fix webhook signature validation** (F-001): Make `_validate_signature` raise an exception on invalid signature. This is a single-line change with massive security impact.
2. **CRITICAL — Remove dead backdoor** (F-003): Delete `authenticate_user` from `security.py`.
3. **CRITICAL — Replace `float` with `Decimal` for money** (F-002): This is a cross-cutting refactor. Start with `models.py`, then update `services/orders.py`, `services/pricing.py`, and `services/payments.py`. Use MongoDB `Decimal128` or integer cents.
4. **HIGH — Replace `python-jose` with `PyJWT`** (F-004): Update `security.py` and `requirements.txt`.
5. **HIGH — Add rate limiting to all write endpoints** (F-007): Focus on `/auth/register`, `/payments/webhook`, `/orders/`, and admin endpoints.
6. **HIGH — Sanitize regex inputs and whitelist `sort_by`** (F-008, F-010): Add input validation helpers.
7. **HIGH — Add HTTP security headers middleware** (F-006): Create a small Starlette middleware.
8. **MEDIUM — Harden Docker and docker-compose** (F-012, F-013): Add non-root user, remove exposed DB ports, pin versions, use `.env` for credentials.
9. **MEDIUM — Expand audit logging** (F-014): Add events for all admin actions, payment failures, and stock changes.
10. **MEDIUM — Implement password reset and email verification** (F-015): Add endpoints and email templates.
11. **LOW — Fix stale documentation** (F-019): Update `openspec/config.yaml`.
12. **LOW — Lock dependency versions** (F-020): Run `pip freeze` and commit a lock file.

### Suggested PR Breakdown

| PR | Scope | Findings | Estimated Lines |
|----|-------|----------|-----------------|
| #1 | Webhook security + dead code | F-001, F-003 | ~50 |
| #2 | Auth hardening | F-004, F-009, F-015, F-017 | ~300 |
| #3 | Input validation + rate limiting | F-007, F-008, F-010 | ~200 |
| #4 | Infrastructure hardening | F-005, F-006, F-011, F-012, F-013, F-016, F-019, F-021, F-025 | ~150 |
| #5 | Financial precision refactor | F-002 | ~400 |
| #6 | Audit logging + idempotency | F-014, F-022 | ~200 |

*Note: PR #5 (Decimal refactor) is the largest and should be isolated to avoid review fatigue.*
