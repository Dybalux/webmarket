# Proposal: Monetary Precision — `float` → `Decimal` + MongoDB `Decimal128`

## Intent

PR #5 of the 6-PR security remediation plan (audit 2026-06-15). Closes the **CRITICAL** finding **F-002** (OWASP A04 Insecure Design): every monetary field is currently `float` in Pydantic models and used in business logic. Python `float` (IEEE 754 double) cannot exactly represent many decimal fractions, so cart totals, dynamic-pricing adjustments, combo savings, and revenue aggregation accumulate rounding error — violating the audit's "balance must match" invariant and creating AFIP-compliance exposure. The audit explicitly flags this as the **largest** PR of the plan and recommends isolation from review-fatigue.

## Scope

### In Scope
- **F-002 model layer**: replace monetary `float` with `Decimal` in `models.py` — `Product.price` / `net_price`, `AdminProduct.net_price`, `ProductUpdate.price` / `net_price`, `CartItemDetailed.price`, `OrderItem.price_at_purchase`, `Order.total_amount` / `shipping_cost`, `PaymentRequest.amount`, `PaymentResponseModel.amount`, `ShippingSettings.central_zone_price` / `remote_zone_price` / `pickup_price`, `Combo.price`, `ComboCreate.price`, `ComboUpdate.price`, `ComboEnriched.price` / `total_items_cost` / `savings`, `BulkPriceUpdate.percentage`, `DynamicPricingSettings.multiplier`. **Keep `abv` (alcohol 0–100) and `profit_percentage` (user-input rate) as `float`** — not money, but audited in the same call to confirm.
- **F-002 services**: convert arithmetic in `services/pricing.py` (`get_adjusted_price`, multiplier persistence), `services/orders.py` (`create_order` `total += price * quantity` + `total + shipping`), `services/orders_helpers.py` (price capture), `services/products.py` (profit% calc `net * (1 + pct/100)`, range filter `$gte/$lte`), `services/shipping.py` (zone prices, default fallback), `services/combos.py` (savings = Σqty·price − combo_price), `services/cart.py` (cart enrichment), `services/payments.py` (MercadoPago `unit_price`).
- **F-002 routers**: `routers/admin.py` (revenue aggregation `$sum: $total_amount`, `bulk-price-update` arithmetic, shipping settings query params), `routers/products.py` (`min_price` / `max_price` query params → `Decimal`).
- **F-002 email + stock helpers**: `email_service.send_new_order_notification` (signature + log + template), `stock_helpers.py` (price projection).
- **F-002 MongoDB layer**: store as `bson.Decimal128`; convert in/out at the service boundary. One-shot migration script `scripts/migrate_floats_to_decimal128.py` (idempotent, `MONGO_LEGACY_FLOATS=1` env fallback during cutover).
- **F-002 tests**: update `tests/conftest.py` (4 product fixture prices), `tests/integration/test_input_validation.py` (`total_amount` fixtures, `sort_by=total_amount`); add new `tests/test_decimal_precision.py` covering the classic float traps (`0.1 + 0.2 != 0.3`, large multiplications, bulk-update rounding, total drift, $sum precision).

### Out of Scope
- Switching to integer-cents (Decimal128 chosen; cents adds a needless conversion layer).
- Currency conversion (single ARS currency).
- Migrating to a new ORM / SQL.
- The other 22 audit findings (covered by other PRs in the plan).
- Changing admin revenue display format (just precision; the value is still rounded to 2 dp).

## Capabilities

### New Capabilities
- `monetary-precision`: Pydantic `Decimal` (12 digits, 2 places) for every monetary field; `bson.Decimal128` storage; `Decimal` arithmetic in services; admin endpoints surface cents exactly; one-shot migration script for legacy doubles.

### Modified Capabilities
- None at the spec/contract level. `service-layer`, `auth-security`, `input-validation`, `infra-hardening`, and `error-normalization` reference monetary fields **as data**, not as requirements — their behaviors (routes, error codes, schemas) are unchanged. Only the internal type changes; the external JSON contract still serializes `Decimal` as a numeric string.

## Approach

- **Models** (`models.py`): monetary fields become `Annotated[Decimal, Field(..., max_digits=12, decimal_places=2)]` via a `Money` alias in the new `utils/money.py`. 12 digits handles up to 9,999,999,999.99 ARS (well above current order volume). Pydantic v2 serializes `Decimal` as a string in JSON — wire format stays numeric for clients that `parseFloat("123.45")`.
- **MongoDB** (`bson.Decimal128`): round-trip via `to_decimal128(value) / from_decimal128(doc)` helpers in `utils/money.py`. `Decimal128` sorts numerically, so `$gte` / `$lte` / range queries keep working without query changes.
- **Arithmetic**: `Decimal * Decimal` and `Decimal + Decimal` only. After every addition or multiplication, `quantize(Decimal("0.01"), ROUND_HALF_EVEN)` (banker's rounding — AFIP-accepted). `multiplier` and `percentage` also become `Decimal` since they multiply money directly.
- **Aggregation** (`routers/admin.py`): `total_revenue = $sum: $total_amount` works on `Decimal128`; convert result with `from_decimal128`; round to 2 dp for display.
- **Bulk price update** (`routers/admin.py:524`): `new_price = base_value * (1 + percentage / Decimal(100))` then `quantize(Decimal("0.01"), ROUND_HALF_EVEN)`.
- **Email** (`email_service.py:57`): `safe_total_amount = html.escape(str(Decimal(total_amount).quantize(Decimal("0.01"))))` — keeps the existing XSS guard, just formats the number first.
- **Migration** (`scripts/migrate_floats_to_decimal128.py`): one-shot `$set` of every monetary field doc from `double` → `Decimal128`. Idempotent (checks BSON type before writing). Backwards: `--downgrade` flag reverts. `MONGO_LEGACY_FLOATS=1` env flag in `config.py` casts `Decimal128` back to `float` at read time until cutover PR lands.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `models.py` (~15 monetary fields, +2 `profit_percentage` / `percentage` borderline) | Modified | `float` → `Decimal` for money; `abv` and `profit_percentage` stay `float` (with explicit comment) |
| `utils/money.py` (new) | New | `Money` type alias, `to_decimal128`, `from_decimal128`, `quantize_money`, `MONGO_LEGACY_FLOATS` flag |
| `services/pricing.py` | Modified | `get_adjusted_price` signature `Decimal → Decimal`; `multiplier` persistence |
| `services/orders.py` | Modified | `create_order` accumulation; email total |
| `services/orders_helpers.py` | Modified | `price_at_purchase` capture |
| `services/products.py` | Modified | profit% calc, range filter, `get_product` / `create_product` / `update_product` |
| `services/shipping.py` | Modified | zone prices, default fallback |
| `services/combos.py` | Modified | savings arithmetic, enrichment |
| `services/cart.py` | Modified | cart enrichment price |
| `services/payments.py` | Modified | MercadoPago `unit_price` payload (cast `Decimal → float` for SDK, with explicit comment) |
| `routers/admin.py` | Modified | revenue `$sum`, `bulk-price-update` arithmetic, shipping settings query |
| `routers/products.py` | Modified | `min_price` / `max_price` query params |
| `email_service.py` | Modified | signature, log, template total format |
| `stock_helpers.py` | Modified | price projection |
| `config.py` | Modified | `MONGO_LEGACY_FLOATS: bool = False` |
| `scripts/migrate_floats_to_decimal128.py` (new) | New | one-shot idempotent migration with `--downgrade` |
| `tests/conftest.py` | Modified | 4 product fixture prices |
| `tests/integration/test_input_validation.py` | Modified | order total fixtures; `sort_by=total_amount` |
| `tests/test_decimal_precision.py` (new) | New | F-002 regression suite (~10–15 tests) |
| `README.md` | Modified | update example payloads (`"price": 1200.00`) and data model schema |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **400-line budget blown** — total ~950–1350 LOC | High | **4 chained PRs** (see strategy below). |
| Existing float docs in prod | High | Idempotent migration script; `MONGO_LEGACY_FLOATS=1` keeps reads working until cutover. |
| `Decimal * float` silently returns `float` (loss) | Med | Custom `field_validator` rejects `float` in monetary fields (debug aid); type-check at design time. |
| `bson.Decimal128` JSON serialization breaks clients | Low | Pydantic v2 emits string; `parseFloat("123.45")` works in JS. Document in OpenAPI. |
| `mongomock-motor` may not support `Decimal128` | Med | Verify at design time; either upgrade `mongomock>=4.1` or wrap at the mock boundary. |
| `mercadopago` SDK expects `float` for `unit_price` | Med | Explicit `float(price_at_purchase.quantize(Decimal("0.01")))` cast at SDK boundary with comment. |
| Precision change visible to admin (e.g. revenue now `1.00` not `0.9999999`) | Low | Expected and correct — call it out in the verify report and announce in the changelog. |
| Bulk-update rounding edge cases | Low | `ROUND_HALF_EVEN` matches accounting convention; covered by tests. |
| Every money-touching test needs an update | Med | Centralize `make_price("100.00")` helper; do it once in `conftest.py`. |
| Backwards-compat during migration window | Med | `MONGO_LEGACY_FLOATS=1` env flag gates the fallback; removed in PR 5d. |

## Rollback Plan

- **Per-PR revert**: revert the merged PR. No data loss (migration script is non-destructive; new field type is written but old type isn't deleted by BSON).
- **Code-only revert (pre-migration)**: app keeps working via `MONGO_LEGACY_FLOATS=1` cast. Set the flag, redeploy the previous image.
- **Post-migration revert**: re-run the migration script with `--downgrade`, or restore from the pre-cutover backup. **Migration ships in the final PR (5d)** so partial state is impossible.
- **Documented in `MANUAL_SMOKE.md`**: list the env flag, the script flags, and the per-PR revert command.

## Dependencies

- `bson.Decimal128` — already in `pymongo` (transitive via `motor==3.7`).
- `decimal` — Python stdlib.
- `pydantic>=2.11` — already pinned; `Decimal` field type supported natively with `max_digits` / `decimal_places`.
- No new third-party packages.

## Success Criteria

- [ ] `grep -rn ': float =' models.py | grep -E 'price|amount|cost|multiplier|percentage|savings' | grep -v abv` returns 0 lines
- [ ] `Decimal("0.1") + Decimal("0.2") == Decimal("0.3")` in a regression test
- [ ] `create_order` with 100 × `Decimal("19.99")` → `total_amount == Decimal("2000.99")` (not `2000.989999...`)
- [ ] `get_adjusted_price(Decimal("1000.00"), multiplier=Decimal("1.10")) == Decimal("1100.00")` exactly
- [ ] `bulk-price-update percentage=Decimal("10.0")` on `net_price=Decimal("500.00")` → `price=Decimal("550.00")` exactly
- [ ] `mongomock-motor` (or replacement) accepts `Decimal128` round-trip; new test passes
- [ ] `GET /admin/stats` revenue returns `Decimal` rounded to 2 places (no float drift)
- [ ] `pytest tests/ -v --tb=short` exits 0 (target: 230+ tests)
- [ ] Migration script is idempotent + validated against staging data before prod
- [ ] `MONGO_LEGACY_FLOATS` flag removed in PR 5d

## Chained PR Strategy (REQUIRED — 400-line guard will be exceeded)

Total: **~950–1350 LOC**. Split into 4 chained PRs, each ≤400 LOC. Pattern follows PR #3 (`input-validation`, 3-PR chain). Delivery: `auto-chain` (default).

| PR | Scope | ~LOC | Risk |
|----|-------|------|------|
| **5a — Foundation** | New `utils/money.py`; `models.py` monetary fields → `Decimal`; Pydantic round-trip tests; no service changes yet (arithmetic is still float at the service boundary; models coerce internally). | 250–350 | Low |
| **5b — Services arithmetic** | Convert arithmetic in all 8 services + `cart.py` + `email_service.py` signature + `stock_helpers.py`. No router changes. | 300–400 | Med |
| **5c — Routers + tests** | `admin.py` (revenue `$sum`, bulk-update, shipping settings query); `products.py` range; all test fixtures updated; new `tests/test_decimal_precision.py`. | 250–350 | Med |
| **5d — Migration + cutover** | `scripts/migrate_floats_to_decimal128.py` (idempotent + `--downgrade`); remove `MONGO_LEGACY_FLOATS` flag; README + `MANUAL_SMOKE.md`; archive. | 150–250 | Med |

**Feature Branch Chain**: PR 5a targets `dev`; PR 5b targets `feature/decimal-5a`; PR 5c targets `feature/decimal-5b`; PR 5d targets `feature/decimal-5c`. Each slice has a clear start, finish, autonomous scope, verification (`pytest`), and reasonable rollback (revert one PR).

**Pre-merge per PR**: run `pytest tests/ -v --tb=short`, confirm 0 new failures, confirm `git diff --stat` ≤ 400 lines.

## References

- `openspec/audits/security-audit-2026-06-15.md` (F-002; PR #5 of 6; §Roadmap row #5; §Implementation Plan #3 CRITICAL; OWASP A04 mapping)
- Exemplar for chained PRs: `openspec/changes/archive/2026-07-27-input-validation/` (3-PR chain pattern)
- Previous PRs in this plan: #1 (webhook+backdoor), #2 (auth), #3 (input-validation), #4 (infra) — all merged
- Python Decimal docs: `https://docs.python.org/3/library/decimal.html` (quantize, ROUND_HALF_EVEN, Context)
- MongoDB Decimal128: `https://www.mongodb.com/docs/manual/reference/bson-types/#decimal128`
