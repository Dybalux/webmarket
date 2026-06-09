# Stock Control Tests Specification

## Purpose

Define the behavioral test contract for webmarket's stock control system. The system spans five files (`stock_helpers.py`, `routers/orders.py`, `routers/inventory.py`, `routers/cart.py`, `routers/products.py`, `routers/admin.py`) and currently has zero test coverage. This spec organizes tests into three PR-aligned layers — unit, integration, endpoint — each adding regression protection for a slice of the stock pipeline.

Two known production bugs (race condition in `create_order`, indentation bug in `update_order_status`) are **out of scope** for this change. Tests that exercise those code paths MUST be marked `pytest.mark.xfail` with a TODO referencing the follow-up `fix-stock-bugs` change.

`mongomock-motor` does NOT support MongoDB transactions. The `stock_helpers.py` transactional path (`validate_and_reserve_stock` + `update_stock_atomic` chained within a `session`) cannot be verified end-to-end. Transactional code paths are tested as **unit tests with mocked sessions**; true multi-document commit semantics are NOT verified by this suite.

## Requirements

### Requirement: Product.stock Model Validation

The Pydantic `Product` model MUST reject negative stock at the model layer and MUST accept non-negative integers.

#### Scenario: Negative stock is rejected

- GIVEN a Pydantic `Product` schema
- WHEN construction is attempted with `stock=-1`
- THEN a `ValidationError` is raised
- AND the field error references the `ge=0` constraint

#### Scenario: Zero stock is accepted

- GIVEN a Pydantic `Product` schema
- WHEN construction is attempted with `stock=0`
- THEN the model is created successfully
- AND `stock` round-trips to `0`

### Requirement: InventoryAlert Model

The `InventoryAlert` Pydantic model MUST accept `product_id` as a string, plus `current_stock`, `threshold`, `message`, and `timestamp` fields.

#### Scenario: Alert is created with required fields

- GIVEN valid alert data
- WHEN an `InventoryAlert` is constructed
- THEN `product_id`, `current_stock`, `threshold`, `message`, `timestamp` are populated
- AND the model serializes to a JSON-compatible dict

### Requirement: OrderItem and CartItem Stock Fields

`OrderItem` and `CartItem` Pydantic models MUST validate `quantity` as a positive integer (`gt=0`).

#### Scenario: Zero quantity is rejected

- GIVEN an `OrderItem` schema
- WHEN construction is attempted with `quantity=0`
- THEN a `ValidationError` is raised

#### Scenario: Positive quantity is accepted

- GIVEN a `CartItem` schema
- WHEN construction is attempted with `quantity=3`
- THEN the model is created successfully

### Requirement: validate_and_reserve_stock Unit Tests

`stock_helpers.validate_and_reserve_stock(session, products_collection, items)` MUST be tested with a mocked `AsyncIOMotorClientSession` and a real `mongomock-motor` collection. The function MUST validate every item, return early on the first invalid entry, and raise a domain-specific exception on insufficient stock.

#### Scenario: Valid product and sufficient stock

- GIVEN a product with `stock=10` and an item requesting `quantity=3`
- WHEN `validate_and_reserve_stock` is called
- THEN it returns successfully with no exception
- AND no DB write occurs (validation only)

#### Scenario: Invalid product ID

- GIVEN an item referencing a non-existent product ID
- WHEN `validate_and_reserve_stock` is called
- THEN it raises a "product not found" exception
- AND the exception message identifies the missing product ID

#### Scenario: Insufficient stock

- GIVEN a product with `stock=2` and an item requesting `quantity=5`
- WHEN `validate_and_reserve_stock` is called
- THEN it raises a "insufficient stock" exception
- AND the exception message identifies the product and requested vs available quantity

#### Scenario: Multi-item batch validates all items

- GIVEN three items referencing three products with sufficient stock each
- WHEN `validate_and_reserve_stock` is called
- THEN it returns successfully
- AND the full list is processed (no early exit on first valid item)

### Requirement: update_stock_atomic Unit Tests

`stock_helpers.update_stock_atomic(session, products_collection, items)` MUST decrement stock with a `$gte` guard and return a signal that lets callers detect a race condition (`modified_count == 0`).

#### Scenario: Successful decrement

- GIVEN a product with `stock=10` and a decrement request for `quantity=3`
- WHEN `update_stock_atomic` is called
- THEN the product's stock becomes `7`
- AND the function returns a success result

#### Scenario: Race condition detected

- GIVEN a product with `stock=2` and a decrement request for `quantity=5`
- WHEN `update_stock_atomic` is called
- THEN `modified_count` is `0`
- AND the caller can detect the race and raise a conflict
- AND the product's stock is unchanged

### Requirement: rollback_stock Unit Tests

`stock_helpers.rollback_stock(session, products_collection, items)` MUST increment stock by the given quantity for every item, regardless of current stock level.

#### Scenario: Successful restoration

- GIVEN a product with `stock=7` and a rollback request for `quantity=3`
- WHEN `rollback_stock` is called
- THEN the product's stock becomes `10`
- AND no exception is raised

### Requirement: check_and_create_alert Threshold Logic

`routers/inventory.check_and_create_alert` MUST create an alert when `current_stock <= LOW_STOCK_THRESHOLD` (10) and MUST NOT create a duplicate alert for the same `(product_id, message)` pair.

#### Scenario: Alert created at threshold

- GIVEN a product with `stock=10` and no prior alert
- WHEN `check_and_create_alert` is called after a stock drop to `10`
- THEN a new alert document is inserted into the alerts collection
- AND `current_stock=10` and `threshold=10` are recorded

#### Scenario: Alert NOT created above threshold

- GIVEN a product with `stock=15`
- WHEN `check_and_create_alert` is called
- THEN no alert document is inserted

#### Scenario: Duplicate alert avoided

- GIVEN a product with `stock=10` and an existing alert whose `message` matches
- WHEN `check_and_create_alert` is called again
- THEN no new alert document is inserted
- AND the alerts collection count is unchanged

### Requirement: Stock Decrement on Order Creation (Integration)

`create_order` MUST decrement product stock after a successful order insert. This code path contains a known race condition bug (separate non-atomic check and decrement) — tests for the happy path MUST be marked `xfail` with TODO referencing `fix-stock-bugs`.

#### Scenario: Single-item order decrements stock

- GIVEN a product with `stock=5` and an authenticated user with an empty cart containing that product
- WHEN the user calls `POST /orders`
- THEN the product's stock is reduced by the ordered quantity
- AND the response includes the new order

#### Scenario: Multi-item order decrements all products

- GIVEN three products with `stock=5` each and a cart with one of each
- WHEN `POST /orders` is called
- THEN each product's stock is reduced by one
- AND the order contains three line items

#### Scenario: Combo order decrements component stocks

- GIVEN a combo composed of two products, each with `stock=5`
- WHEN `POST /orders` is called for that combo
- THEN each component product's stock is reduced by one
- AND the order records the combo as one line item

### Requirement: Stock Restoration on Cancel/Refund (Integration)

`update_order_status` MUST restore stock when an order transitions to `CANCELLED` or `REFUNDED`. This code path contains a known indentation bug — tests MUST be marked `xfail` with TODO referencing `fix-stock-bugs`.

#### Scenario: Cancel reposes stock

- GIVEN a delivered order that decremented stock on creation
- WHEN an admin calls `PUT /orders/admin/{id}/status` with `new_status=CANCELLED`
- THEN each product's stock is incremented by the original ordered quantity
- AND the order's status becomes `CANCELLED`

#### Scenario: Refund reposes stock

- GIVEN a paid order that decremented stock on creation
- WHEN an admin calls `PUT /orders/admin/{id}/status` with `new_status=REFUNDED`
- THEN each product's stock is incremented by the original ordered quantity
- AND the order's status becomes `REFUNDED`

### Requirement: Stock Validation Before Order (Integration)

`create_order` MUST reject the request with HTTP 409 `CONFLICT` when any line item requests more units than are in stock.

#### Scenario: Insufficient stock returns 409

- GIVEN a product with `stock=2` and a cart requesting `quantity=5`
- WHEN `POST /orders` is called
- THEN the response is HTTP 409
- AND the response body identifies the under-stocked product
- AND the product's stock is unchanged (no decrement occurs)

### Requirement: Low Stock Alert on Order (Integration)

When an order causes a product's stock to drop at or below `LOW_STOCK_THRESHOLD` (10), a low-stock alert MUST be created for that product. Duplicate alerts for the same stock level MUST NOT be created.

#### Scenario: Alert created when stock crosses threshold

- GIVEN a product with `stock=12` and an order that will reduce it to `8`
- WHEN the order completes successfully
- THEN a new `InventoryAlert` document exists for the product
- AND the alert records `current_stock=8` and `threshold=10`

#### Scenario: Duplicate alert not created at same stock level

- GIVEN a product with `stock=8` and an existing alert whose `message` matches the new alert
- WHEN a second order further reduces stock but the alert `message` would be identical
- THEN no new alert is inserted
- AND the alerts collection count for that product is unchanged

### Requirement: Product Listing Filter (Integration)

`GET /products` MUST exclude out-of-stock products by default and MUST include them when the caller is an admin passing `include_out_of_stock=true`.

#### Scenario: Out-of-stock products hidden by default

- GIVEN a catalog with one in-stock product and one zero-stock product
- WHEN an anonymous or non-admin caller calls `GET /products`
- THEN only the in-stock product is returned
- AND the zero-stock product is omitted

#### Scenario: Out-of-stock products visible to admin

- GIVEN a catalog with one in-stock product and one zero-stock product
- WHEN an admin calls `GET /products?include_out_of_stock=true`
- THEN both products are returned

### Requirement: Admin Inventory Endpoints (Endpoint)

`PUT /inventory/{id}/stock` and `PUT /inventory/{id}/stock/add` MUST be admin-only, MUST update the target product's stock, and MUST trigger `check_and_create_alert`. `GET /inventory/alerts` MUST be admin-only and MUST return alerts sorted by `timestamp` descending.

#### Scenario: Admin sets absolute stock

- GIVEN a product with `stock=20` and an authenticated admin
- WHEN the admin calls `PUT /inventory/{id}/stock` with body `{"stock": 5}`
- THEN the product's stock becomes `5`
- AND a low-stock alert is created (stock ≤ threshold)

#### Scenario: Admin adds stock

- GIVEN a product with `stock=5` and an existing low-stock alert
- WHEN the admin calls `PUT /inventory/{id}/stock/add` with body `{"quantity": 20}`
- THEN the product's stock becomes `25`
- AND no new alert is created (stock now above threshold)

#### Scenario: Non-admin cannot modify stock

- GIVEN a non-admin authenticated user
- WHEN the user calls `PUT /inventory/{id}/stock`
- THEN the response is HTTP 403

#### Scenario: List alerts sorted by timestamp desc

- GIVEN three alerts with different `timestamp` values
- WHEN an admin calls `GET /inventory/alerts`
- THEN the response contains the three alerts
- AND the first element is the most recent

### Requirement: Cart Stock Validation Endpoint (Endpoint)

`GET /cart/validate-stock` MUST return a per-item availability report for the caller's cart and a top-level `all_available` boolean.

#### Scenario: All items in stock

- GIVEN a cart with two products, each with sufficient stock
- WHEN the user calls `GET /cart/validate-stock`
- THEN the response returns `all_available=true`
- AND each item reports `available=true` with the current stock

#### Scenario: One item out of stock

- GIVEN a cart with two products, one with insufficient stock
- WHEN the user calls `GET /cart/validate-stock`
- THEN the response returns `all_available=false`
- AND the under-stocked item reports `available=false` with the available quantity

### Requirement: Known Bug Markers

Tests that exercise code paths containing the race condition bug in `create_order` or the indentation bug in `update_order_status` MUST be marked with `pytest.mark.xfail(strict=False, reason="Bug exercised; see fix-stock-bugs change")`. The marker MUST NOT be removed until the follow-up `fix-stock-bugs` change is merged and the bugs are fixed.

#### Scenario: Race condition test is xfail

- GIVEN a test for `POST /orders` that exercises the race condition code path
- WHEN the test is run against the current (buggy) implementation
- THEN pytest reports the test as `xfail`
- AND the test does not contribute a failure to the overall suite result

#### Scenario: Indentation bug test is xfail

- GIVEN a test for `PUT /orders/admin/{id}/status` cancel flow
- WHEN the test is run against the current (buggy) implementation
- THEN pytest reports the test as `xfail`

### Requirement: Transactional Path Gap Documentation

`stock_helpers.py` functions that depend on `AsyncIOMotorClientSession` MUST be tested with a mocked session object. The test docstring or comment for each transactional test MUST state that `mongomock-motor` does not support transactions and that true multi-document atomicity is not verified by this suite.

#### Scenario: Transactional test documents the gap

- GIVEN a unit test for `validate_and_reserve_stock` or `update_stock_atomic`
- WHEN the test is read
- THEN a comment or docstring states that mongomock-motor does not support transactions
- AND the test does not assert atomicity across multiple documents
