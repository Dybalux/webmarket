# Auth Security Specification

## Purpose

Behavioral contract for JWT library migration, password policy, password reset flow, and per-account lockout (findings F-004, F-009, F-015 partial, F-017). Email verification is explicitly deferred.

## Requirements

### Requirement: JWT Library Swap

The system MUST use PyJWT>=2.8.0. The system MUST NOT import `python-jose`. Encoding MUST specify `algorithms=["HS256"]`. Algorithm `none` MUST NOT be accepted. Decoding MUST catch `jwt.PyJWTError`. Pre-swap tokens MUST remain valid.

#### Scenario: Pre-swap tokens validate

- GIVEN a JWT signed with HS256 by python-jose
- WHEN decoded by the PyJWT-based decoder
- THEN the payload matches the original claims

#### Scenario: Algorithm none rejected

- GIVEN a token with `alg: none`
- WHEN decoded
- THEN `PyJWTError` is raised, request rejected with 401

#### Scenario: No jose imports remain

- GIVEN production source after migration
- WHEN `grep -rn "jose" --include="*.py"` runs
- THEN zero matches in production code

### Requirement: Password Policy

At registration and reset, passwords MUST have: min 12 chars, one uppercase, one lowercase, one digit, one special character. Passwords in the embedded common-password blocklist MUST be rejected. Violations MUST return 422 with field detail. Existing passwords MUST NOT be retroactively validated.

#### Scenario: Strong password accepted

- GIVEN registration with password `MyD0g$W0rld!23`
- WHEN validated
- THEN passes, user created

#### Scenario: Common password rejected

- GIVEN registration with a blocklisted password
- WHEN validated
- THEN 422, detail indicates password too common

#### Scenario: Short password rejected

- GIVEN registration with password `Ab1!`
- WHEN validated
- THEN 422 with character-count detail

#### Scenario: Existing passwords not re-checked

- GIVEN a user with a pre-policy 8-char password
- WHEN they log in
- THEN authentication succeeds without policy check

### Requirement: Password Reset Flow

`POST /auth/forgot-password` MUST return 202 regardless of email existence. `POST /auth/reset-password` MUST accept a token and new password. Tokens MUST be `secrets.token_urlsafe(32)`, stored as SHA-256 hashes, expire after 1 hour, single-use. New password MUST satisfy password policy. Email delivery MUST use existing Resend pattern.

#### Scenario: Known email triggers email

- GIVEN registered user `user@example.com`
- WHEN `POST /auth/forgot-password` called
- THEN 202 returned, reset email sent

#### Scenario: Unknown email returns identical response

- GIVEN no user with `unknown@example.com`
- WHEN `POST /auth/forgot-password` called
- THEN 202 returned (identical), no email sent

#### Scenario: Valid token succeeds

- GIVEN valid unexpired reset token
- WHEN `POST /auth/reset-password` with token and compliant password
- THEN password updated, token consumed

#### Scenario: Expired token rejected

- GIVEN token issued >1 hour ago
- WHEN `POST /auth/reset-password` called
- THEN rejected with 400

#### Scenario: Reused token rejected

- GIVEN already-consumed token
- WHEN `POST /auth/reset-password` called
- THEN rejected with 400

#### Scenario: Weak password rejected at reset

- GIVEN valid token
- WHEN reset called with password `123`
- THEN 422 with policy detail

### Requirement: Account Lockout

The system MUST track per-account consecutive failed logins in Redis. After 5 consecutive failures, the account MUST be locked for 15 minutes. Successful login MUST reset the counter. Lockout MUST complement (not replace) the IP-based `RateLimiter`. The Redis client MUST be injectable via FastAPI dependency injection for test environments.

#### Scenario: Five failures lock account

- GIVEN 4 consecutive failed logins for an account
- WHEN 5th failure occurs
- THEN subsequent attempts return 423 with lockout duration

#### Scenario: Success resets counter

- GIVEN 3 failed attempts
- WHEN successful login occurs
- THEN counter resets to zero

#### Scenario: Lockout expires

- GIVEN locked account (5 failures)
- WHEN 15 minutes elapse
- THEN next attempt processed normally

#### Scenario: IP rate limiter independent

- GIVEN lockout active
- WHEN IP rate limit exceeded
- THEN IP limiter responds independently

#### Scenario: Redis injectable in tests

- GIVEN test environment without lifespan Redis
- WHEN lockout dependency resolves
- THEN test-provided fake Redis is used
