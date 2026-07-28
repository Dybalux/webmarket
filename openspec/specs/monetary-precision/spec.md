# Monetary Precision Specification

## Purpose

Guarantee exact decimal arithmetic for all monetary values across the system — Pydantic models, service-layer calculations, MongoDB persistence, and API wire format — eliminating IEEE 754 float rounding errors that violate balance invariants and AFIP compliance.

## Requirements

### Requirement: Decimal Field Types

All monetary fields (`price`, `net_price`, `total_amount`, `shipping_cost`, `amount`, `savings`, `total_items_cost`, zone prices) MUST use `Decimal` with `max_digits=12, decimal_places=2`. Non-monetary float fields (`abv`, `profit_percentage`) MAY remain as `float`. Pydantic models MUST reject `float` input for monetary fields via a custom `field_validator`.

#### Scenario: Monetary field accepts valid Decimal string

- GIVEN a Pydantic model with a monetary field `price`
- WHEN instantiated with `price="19.99"`
- THEN `price` MUST be `Decimal("19.99")` with exactly 2 decimal places

#### Scenario: Monetary field rejects float input

- GIVEN a Pydantic model with a monetary field `price`
- WHEN instantiated with `price=19.99` (Python float)
- THEN a `ValidationError` MUST be raised

### Requirement: Decimal Arithmetic

All monetary arithmetic in services MUST operate exclusively on `Decimal` operands. Multiplication, addition, and subtraction MUST preserve precision. Every result MUST be quantized to 2 decimal places using `ROUND_HALF_UP`.

#### Scenario: Order total accumulation is exact

- GIVEN 100 units at `Decimal("19.99")` each
- WHEN `total_amount` is computed as `sum(price * quantity)`
- THEN `total_amount` MUST equal `Decimal("1999.00")` exactly (no float drift)

#### Scenario: Classic float trap is avoided

- GIVEN `Decimal("0.1") + Decimal("0.2")`
- WHEN the sum is quantized
- THEN the result MUST equal `Decimal("0.30")`

#### Scenario: Bulk price update preserves precision

- GIVEN `net_price = Decimal("500.00")` and `percentage = Decimal("10.0")`
- WHEN `new_price = net_price * (1 + percentage / 100)` is quantized with `ROUND_HALF_UP`
- THEN `new_price` MUST equal `Decimal("550.00")` exactly

### Requirement: MongoDB Decimal128 Storage

Monetary values MUST be stored as `bson.Decimal128` in MongoDB. Reads MUST convert `Decimal128` back to `Decimal` at the service boundary. Legacy `float` documents MUST be handled transparently during migration.

#### Scenario: Write and read round-trip preserves value

- GIVEN a document with `total_amount = Decimal("1234.56")`
- WHEN stored to MongoDB and read back
- THEN the value MUST be `Decimal("1234.56")` (no precision loss)

#### Scenario: Legacy float document is handled during migration

- GIVEN a document where `total_amount` is stored as BSON `double`
- WHEN the migration script runs
- THEN the field MUST be converted to `Decimal128` with equivalent value

### Requirement: API Wire Format

JSON responses MUST serialize `Decimal` values as strings (e.g., `"123.45"`). API inputs MUST accept both string and numeric representations for `Decimal` fields.

#### Scenario: Response serializes Decimal as string

- GIVEN an order with `total_amount = Decimal("2000.99")`
- WHEN the order is returned via `GET /orders/{id}`
- THEN the JSON body MUST contain `"total_amount": "2000.99"` (string, not number)

#### Scenario: Input accepts string for Decimal field

- GIVEN a `POST /products` endpoint with `price` field
- WHEN the request body contains `"price": "1500.00"`
- THEN the model MUST parse it as `Decimal("1500.00")`

#### Scenario: Input accepts number for Decimal field

- GIVEN a `POST /products` endpoint with `price` field
- WHEN the request body contains `"price": 1500`
- THEN the model MUST coerce it to `Decimal("1500.00")`

### Requirement: Migration

A migration script MUST convert all existing `float` monetary values to `Decimal128` in MongoDB. The migration MUST be idempotent (safe to re-run). A rollback mechanism MUST be available to revert `Decimal128` values back to `float`.

#### Scenario: Migration is idempotent

- GIVEN a collection where some documents already have `Decimal128` monetary fields
- WHEN the migration script runs again
- THEN already-migrated documents MUST NOT be modified (BSON type check before write)

#### Scenario: Rollback restores float values

- GIVEN a collection with `Decimal128` monetary fields
- WHEN the migration script runs with `--downgrade`
- THEN all monetary fields MUST be converted back to BSON `double`
