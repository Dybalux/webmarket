# Design: Monetary Precision — `float` → `Decimal` + MongoDB `Decimal128`

## Technical Approach

Swap IEEE 754 `float` for `Decimal` on every monetary field, persisted as `bson.Decimal128`. One `Money` alias in a new `utils/money.py` carries validation, BSON conversion, and rounding; services do `Decimal`-only arithmetic quantized to 2 dp; a one-shot idempotent migration converts legacy doubles in the final chained PR. No new dependencies (`decimal` stdlib, `bson` via pymongo).

**Sources**: [Proposal](proposal.md) · [Spec](../../specs/monetary-precision/spec.md) · `openspec/audits/security-audit-2026-06-15.md`

## Architecture Decisions

### ADR-1: `Money` annotated alias in `utils/money.py`

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2), BeforeValidator, AfterValidator]` | One definition for ~20 fields; mirrors `PyObjectId` centralization; Pydantic v2 native | **Chosen** |
| Custom core-schema class | ~50 LOC of plumbing | Rejected — Annotated suffices |
| Plain `Decimal` per field | 20 validator copies drift | Rejected |

`BeforeValidator`: `Decimal128 → .to_decimal()` (DB reads). `AfterValidator`: rejects Python `float` unless `settings.MONGO_LEGACY_FLOATS`, then coerces via `Decimal(str(v))` — `str()` avoids binary noise. `abv` and `profit_percentage` stay `float` (not money), with comments.

### ADR-2: `bson.Decimal128` storage, explicit conversion at the service boundary

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `decimalize_doc(d)` recursive `Decimal→Decimal128` walk on `model_dump()` at every DB-write site | Explicit, ~15 sites; `Decimal128` sorts numerically so `$gte/$lte/$sum` work unchanged | **Chosen** |
| `TypeCodec`/`CodecOptions` on the client | `mongomock-motor` ignores codec options — test/prod divergence | Rejected |
| String storage | Loses numeric sort and `$sum` | Rejected |
| Integer cents | Conversion layer; proposal rejected | Rejected |

pymongo raises `InvalidDocument` on raw `Decimal`, so conversion is mandatory; the helper makes it one line per write.

### ADR-3: `ROUND_HALF_UP`, not banker's rounding

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `ROUND_HALF_UP` | Spec's RFC-2119 MUST; commercial convention (`500.00 × 1.10 = 550.00`) | **Chosen** |
| `ROUND_HALF_EVEN` (proposal) | Conflicts with spec | Rejected |

Helper: `quantize_money(v)` quantizes to `0.01` after every add/multiply. Spec conflict → Open Questions.

### ADR-4: Preserve `BulkPriceUpdate` fraction semantics (`0.10` = 10%)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Keep `new_price = quantize_money(base * (1 + percentage))`, `percentage: Decimal` | Matches docstring (`"0.10 para 10%"`), `scripts/adjust_prices.py`, admin frontend | **Chosen** |
| Proposal/spec's `1 + percentage / 100` | Silent behavior change — `0.10` would mean 0.1% | Rejected — see Open Questions |

### ADR-5: SDK boundary casts

`services/payments.py:71`: `unit_price=float(quantize_money(price))` — MercadoPago SDK expects `float`; 2-dp quantization first makes the cast lossless. Revenue (`routers/admin.py`): `$sum` over `Decimal128` returns `Decimal128` → `.to_decimal()` → `quantize_money`, replacing `round(total, 2)`.

### ADR-6: One-shot idempotent migration in the final PR (5d)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Script checks BSON type per doc, `$set` only doubles, `--downgrade` reverts | Idempotent, rollback path | **Chosen** |
| Lazy per-read migration | Indefinite mixed state; `$sum` skew | Rejected |

## Data Flow

    Request JSON ──► Money field ──► Decimal (float rejected)
                       │ service arithmetic: Decimal only, quantize_money
                       ▼ model_dump() → decimalize_doc → Decimal128 → MongoDB
    MongoDB → Decimal128 → BeforeValidator → Decimal → JSON string "19.99"

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `utils/money.py` | Create | `Money` alias, `decimalize_doc`, `quantize_money`, `from_decimal128` |
| `models.py` | Modify | ~20 monetary fields → `Money`; `abv`/`profit_percentage` stay `float` |
| `services/pricing.py` | Modify | `get_adjusted_price: Decimal→Decimal`; drop `round(x, 2)` |
| `services/orders.py` | Modify | Total accumulation; `decimalize_doc` on insert |
| `services/orders_helpers.py` | Modify | `price_at_purchase` capture |
| `services/products.py` | Modify | Profit% calc, range filter, writes |
| `services/shipping.py` | Modify | Zone prices, settings writes |
| `services/combos.py` | Modify | Savings arithmetic, writes |
| `services/cart.py` | Modify | Enrichment price |
| `services/payments.py` | Modify | SDK `float` cast + writes |
| `routers/admin.py` | Modify | Revenue `$sum`, bulk-update, shipping `Query` params → `Decimal` |
| `routers/products.py` | Modify | `min_price`/`max_price` → `Decimal` |
| `email_service.py` | Modify | Signature `Decimal`; `html.escape(str(quantize_money(total)))` |
| `stock_helpers.py` | Modify | Price projection |
| `config.py` | Modify | `MONGO_LEGACY_FLOATS: bool = False` |
| `scripts/migrate_floats_to_decimal128.py` | Create | Idempotent migration + `--downgrade` |
| `tests/conftest.py` | Modify | Fixture prices → `Decimal128`; flag on for 5a–5b, off in 5c |
| `tests/integration/test_input_validation.py` | Modify | Order total fixtures |
| `tests/test_decimal_precision.py` | Create | F-002 regression suite (~12 tests) |
| `README.md` | Modify | Example payloads, schema notes |

## Interfaces / Contracts

```python
# utils/money.py
Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2),
                  BeforeValidator(_bson_to_decimal), AfterValidator(_reject_float)]
def quantize_money(v: Decimal) -> Decimal: ...
def decimalize_doc(doc: dict) -> dict: ...   # recursive Decimal→Decimal128
def from_decimal128(v: Any) -> Decimal: ...
```

JSON wire: Pydantic v2 emits `Decimal` as string (`"19.99"`); JS `parseFloat` compatible. Documented in OpenAPI/README.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `Money` validator (rejects float, accepts str/`Decimal128`), `quantize_money`, `decimalize_doc` nesting | `tests/test_decimal_precision.py` |
| Integration | `create_order` 100 × 19.99 exact; bulk-update 500 × 1.10 = 550.00; range filter on `Decimal128`; revenue `$sum` no drift | mongomock-motor (verify `Decimal128` support first) |
| Migration | Idempotency (second run = 0 writes), `--downgrade` round-trip | Seeded mock + staging |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

4 chained PRs: **5a** Foundation (`utils/money.py` + `models.py`); **5b** services arithmetic; **5c** routers + fixtures + regression suite; **5d** migration + flag removal + docs. `MONGO_LEGACY_FLOATS=1` in prod and conftest from 5a until 5d; tests default off. Rollback: per-PR revert; post-5d via `--downgrade` or backup.

## Open Questions

- [ ] Spec's bulk-update scenario uses `percentage=10.0` with `/100`; live API uses fraction semantics (`0.10` = 10%). Design keeps the live contract (ADR-4) — spec scenario MUST be corrected in sdd-spec.
- [ ] Proposal says `ROUND_HALF_EVEN`; spec mandates `ROUND_HALF_UP`. Design follows spec (ADR-3) — confirm with stakeholders.
- [ ] `mongomock-motor==0.0.36` `Decimal128` round-trip unverified — spike in 5a before committing fixtures.
