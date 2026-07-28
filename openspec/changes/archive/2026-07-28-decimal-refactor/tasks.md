# Tasks: Monetary Precision — `float` → `Decimal` + MongoDB `Decimal128`

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 950–1350 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | 5a → 5b → 5c → 5d |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Foundation: `utils/money.py` + `models.py` Decimal fields | PR 5a | `pytest tests/test_decimal_precision.py -v` | N/A — unit tests only | Revert PR 5a; models revert to float, app still works |
| 2 | Services: All 8 services + helpers with Decimal arithmetic | PR 5b | `pytest tests/ -v --tb=short` | N/A — integration tests | Revert PR 5b; services revert to float arithmetic |
| 3 | Routers + Tests: Router updates + regression suite | PR 5c | `pytest tests/ -v --tb=short` | N/A — integration tests | Revert PR 5c; routers revert to float params |
| 4 | Migration + Cutover: Script + flag removal | PR 5d | `pytest tests/ -v --tb=short` | Migration script on staging | Revert PR 5d; re-enable `MONGO_LEGACY_FLOATS` |

## Phase 1: Foundation (PR 5a)

- [x] 1.1 Create `utils/money.py` with `Money` alias, `decimalize_doc`, `quantize_money`, `from_decimal128`
- [x] 1.2 Add `MONGO_LEGACY_FLOATS: bool = False` to `config.py`
- [x] 1.3 Update `models.py` monetary fields to `Money` (~20 fields)
- [x] 1.4 Keep `abv` and `profit_percentage` as `float` with explicit comments
- [x] 1.5 Add `tests/test_decimal_precision.py` with `Money` validator tests (reject float, accept str/`Decimal128`)
- [x] 1.6 Verify `mongomock-motor` `Decimal128` round-trip support

## Phase 2: Services (PR 5b)

- [x] 2.1 Update `services/pricing.py`: `get_adjusted_price` signature `Decimal→Decimal`, drop `round(x, 2)`
- [x] 2.2 Update `services/orders.py`: total accumulation with `decimalize_doc` on insert
- [x] 2.3 Update `services/orders_helpers.py`: `price_at_purchase` capture
- [x] 2.4 Update `services/products.py`: profit% calc, range filter, writes
- [x] 2.5 Update `services/shipping.py`: zone prices, settings writes
- [x] 2.6 Update `services/combos.py`: savings arithmetic, writes
- [x] 2.7 Update `services/cart.py`: enrichment price
- [x] 2.8 Update `services/payments.py`: SDK `float` cast + writes

## Phase 3: Routers + Tests (PR 5c)

- [x] 3.1 Update `routers/admin.py`: revenue `$sum`, bulk-update arithmetic, shipping `Query` params → `Decimal`
- [x] 3.2 Update `routers/products.py`: `min_price`/`max_price` → `Decimal`
- [x] 3.3 Update `email_service.py`: signature `Decimal`; `html.escape(str(quantize_money(total)))`
- [x] 3.4 Update `stock_helpers.py`: price projection
- [x] 3.5 Update `tests/conftest.py`: fixture prices → `Decimal128`
- [x] 3.6 Update `tests/integration/test_input_validation.py`: order total fixtures
- [x] 3.7 Add `tests/test_decimal_precision.py` integration tests (order total, bulk-update, range filter, revenue sum)

## Phase 4: Migration + Cutover (PR 5d)

- [x] 4.1 Create `scripts/migrate_floats_to_decimal128.py`: idempotent migration + `--downgrade`
- [x] 4.2 Remove `MONGO_LEGACY_FLOATS` flag from `config.py`
- [x] 4.3 Update `README.md`: example payloads, schema notes
- [ ] 4.4 Update `MANUAL_SMOKE.md`: env flag, script flags, per-PR revert commands
- [x] 4.5 Verify all tests pass with `MONGO_LEGACY_FLOATS=False`
- [ ] 4.6 Run migration script on staging and validate