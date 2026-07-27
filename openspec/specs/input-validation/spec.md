# Input Validation Specification

## Purpose

Input sanitization and strict request validation (F-008, F-010, F-018, F-026): regex sanitization, sort-field whitelisting, HTML escaping in emails, strict Pydantic models.

## Requirements

### Requirement: Regex Sanitization

The system MUST escape regex special characters (`. * + ? ^ $ { } ( ) | [ ] \`) in user-provided search strings before MongoDB `$regex` queries. Empty or null search values MUST skip the `$regex` clause.

#### Scenario: Search with regex metacharacters sanitized

- GIVEN a request with `search=C++`
- WHEN the value reaches a `$regex` query
- THEN metacharacters are escaped, preventing ReDoS
- AND the query matches literal "C++"

#### Scenario: Empty search skips regex clause

- GIVEN `search=""` or `search=null`
- WHEN the query is built
- THEN no `$regex` clause is added

#### Scenario: Normal search string passes through

- GIVEN `search=laptop`
- WHEN the query is built
- THEN `$regex` matches "laptop" case-insensitively

### Requirement: Sort Field Whitelist

The system MUST validate `sort_by` against a per-endpoint whitelist. Unknown fields MUST return HTTP 400. Users whitelist: `created_at`, `username`, `email`, `role`, `updated_at`. Orders whitelist: `created_at`, `total_amount`, `status`.

#### Scenario: Valid sort field accepted

- GIVEN `/admin/users?sort_by=username`
- WHEN processed
- THEN results sorted by username

#### Scenario: Invalid sort field rejected

- GIVEN `/admin/users?sort_by=password_hash`
- WHEN processed
- THEN HTTP 400 with invalid sort field message

#### Scenario: Orders endpoint whitelist enforced

- GIVEN `/admin/orders?sort_by=customer_name`
- WHEN processed
- THEN HTTP 400 (field not in orders whitelist)

#### Scenario: Missing sort_by uses default

- GIVEN `/admin/users` without `sort_by`
- WHEN processed
- THEN default sorting applied

### Requirement: HTML Escaping in Email Templates

The system MUST escape all user-provided values in HTML email templates using `html.escape()`. Applies to both `send_new_order_notification` and `send_password_reset_email`. Values: `user_email`, `order_id`, `total_amount`, `payment_method`.

#### Scenario: XSS attempt in email rendered as text

- GIVEN email `<script>alert(1)</script>`
- WHEN order notification sent
- THEN body contains escaped `&lt;script&gt;alert(1)&lt;/script&gt;`
- AND no executable script tag present

#### Scenario: Normal values rendered correctly

- GIVEN email `alice@example.com`
- WHEN password reset email sent
- THEN email address rendered unmodified

#### Scenario: Special HTML characters escaped

- GIVEN `payment_method=<img src=x onerror=alert(1)>`
- WHEN order notification sent
- THEN angle brackets escaped to `&lt;` and `&gt;`

### Requirement: Strict Pydantic Request Models

All request models MUST inherit from `BaseRequestModel` with `extra="forbid"`. Unexpected fields MUST return HTTP 422. `Settings` MAY use `extra="ignore"` for env var flexibility. Response models unaffected.

#### Scenario: Extra field in request rejected

- GIVEN POST `/auth/register` with `{"email":"a@b.com","password":"X","extra":"y"}`
- WHEN validated
- THEN HTTP 422 with extra fields not permitted detail

#### Scenario: Valid request accepted

- GIVEN POST with only defined fields
- WHEN validated
- THEN processed normally

#### Scenario: Settings ignores unknown env vars

- GIVEN env var `UNKNOWN_VAR=foo`
- WHEN Settings instantiated
- THEN variable ignored, no error

#### Scenario: Response models unaffected

- GIVEN response model without `extra="forbid"`
- WHEN serializing output
- THEN extra fields included as before
