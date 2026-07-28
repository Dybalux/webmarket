# Infra Hardening Specification

## Purpose

Infrastructure security contracts: CORS, HTTP security headers, API docs gating, container hardening, environment enforcement, and HTTPS redirection.

## Requirements

### Requirement: CORS Lockdown

The system MUST restrict CORS `allow_methods` to exactly `GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `OPTIONS`.
The system MUST restrict CORS `allow_headers` to exactly `Authorization`, `Content-Type`, `X-Requested-With`.
The system MUST NOT use wildcard `*` in allowed origins in any environment.

#### Scenario: Preflight with allowed method and header

- GIVEN the application is running
- WHEN a CORS preflight requests method `PUT` and header `Authorization`
- THEN `Access-Control-Allow-Methods` MUST contain only the six allowed methods
- AND `Access-Control-Allow-Headers` MUST contain only the three allowed headers

#### Scenario: Wildcard origin rejected

- GIVEN the application is running in development
- WHEN origins are inspected
- THEN no origin entry MUST contain wildcard `*`

### Requirement: Security Headers

The system MUST set `X-Frame-Options: DENY` on every HTTP response.
The system MUST set `X-Content-Type-Options: nosniff` on every HTTP response.
The system MUST set `Referrer-Policy: strict-origin-when-cross-origin` on every HTTP response.
The system MUST set `Permissions-Policy: geolocation=(), microphone=()` on every HTTP response.
The system MUST set `Strict-Transport-Security` with a positive `max-age` when `ENV=production`.

#### Scenario: Security headers present on normal response

- GIVEN the application is running
- WHEN a `GET /health` request is made
- THEN the response MUST include `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Permissions-Policy: geolocation=(), microphone=()`

#### Scenario: HSTS in production only

- GIVEN `ENV=production`
- WHEN any HTTP response is returned
- THEN the response MUST include `Strict-Transport-Security` with a positive `max-age`
- AND when `ENV=development`, the response MUST NOT include `Strict-Transport-Security`

### Requirement: API Documentation Gating

The system MUST disable `/docs` and `/redoc` endpoints when `ENV=production`.
The system MUST disable the OpenAPI schema endpoint when `ENV=production`.

#### Scenario: Docs disabled in production

- GIVEN `ENV=production`
- WHEN a `GET /docs` or `GET /redoc` request is made
- THEN the response MUST be `404 Not Found`

#### Scenario: Docs available in development

- GIVEN `ENV=development`
- WHEN a `GET /docs` request is made
- THEN the response MUST be `200 OK`

### Requirement: Non-root Container

The Dockerfile MUST run the application process as a non-root user.
The Dockerfile MUST pin the base image to a specific version tag.

#### Scenario: Container runs as non-root

- GIVEN the Docker image is built
- WHEN `docker inspect` is executed on the image
- THEN the `User` field MUST be a non-root username (not `root`, not empty)

### Requirement: Docker Compose Hardening

MongoDB and Redis MUST NOT expose ports to the host network.
Database credentials MUST be sourced from environment variables, not hardcoded.
All service images MUST be pinned to specific version tags (no `:latest`).
Redis MUST require password authentication.

#### Scenario: No host port exposure

- GIVEN the docker-compose configuration
- WHEN `docker compose config` is executed
- THEN the MongoDB and Redis services MUST NOT have host port mappings

#### Scenario: Pinned image versions

- GIVEN the docker-compose configuration
- WHEN image tags are inspected
- THEN MongoDB MUST use `mongo:7.0` and Redis MUST use `redis:7.2-alpine`

### Requirement: ENV Required

The `ENV` environment variable MUST be required with no default value.
The application MUST fail fast at startup if `ENV` is not set.

#### Scenario: Missing ENV causes startup failure

- GIVEN `ENV` is not set in the environment
- WHEN the application starts
- THEN the process MUST exit with a non-zero status and a validation error

### Requirement: HTTPS Redirect

The system MUST redirect HTTP requests to HTTPS when `ENV=production`.

#### Scenario: HTTP redirected to HTTPS in production

- GIVEN `ENV=production`
- WHEN an HTTP request is received (non-HTTPS)
- THEN the system MUST respond with a `307` redirect to the equivalent HTTPS URL

#### Scenario: No redirect in development

- GIVEN `ENV=development`
- WHEN an HTTP request is received
- THEN the system MUST NOT issue an HTTPS redirect
