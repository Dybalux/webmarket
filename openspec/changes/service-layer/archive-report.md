# Service-Layer Change — Archive Report

**Archived on**: 2026-06-12
**Archived by**: sdd-archive sub-agent
**Change status**: ARCHIVED (closed)

## Change Summary

The service-layer refactor introduced a `services/` directory to webmarket's flat FastAPI structure, extracting business logic from 7 routers into 11 service modules. This is a behavior-preserving refactor with API 1:1 byte-identity (zero observable change).

## PR List (in merge order)

| PR | Title | Branch | LOC net | Merged |
|----|-------|--------|---------|--------|
| #0 | cleanup: remove orders_backup.py | chore/remove-orders-backup | -423 | yes |
| #1a | services: add domain exception hierarchy | feat/service-layer-exceptions | +222 | yes |
| #1b | services: add InventoryService | feat/service-layer-inventory | +160 | yes |
| #2 | services: add PricingService | feat/service-layer-pricing | +118 | yes |
| #3 | services: add CartService | feat/service-layer-cart | +282 | yes |
| #4 | services: add OrderService, PaymentService, ShippingService | feat/service-layer-orders | -13 | yes |
| #5a | services: add ProductsService (gap closure) | feat/service-layer-products | +135 | yes |
| #5b-1 | services: add CombosService (gap closure) | feat/service-layer-combos-service | +349 | yes |
| #5b-2a | routers: route combos public endpoints (gap closure) | feat/service-layer-combos-public | -83 | yes |
| #5b-2b | routers: route combos admin endpoints (gap closure) | feat/service-layer-combos-admin | -10 | yes |

Total: 10 PRs across 5 phases + gap closure.

## Final State

### Services Layer (NEW)
- 11 modules: `__init__.py`, `exceptions.py`, `inventory.py`, `pricing.py`, `cart.py`, `orders.py`, `orders_helpers.py`, `payments.py`, `shipping.py`, `products.py`, `combos.py`
- 36 public functions + 2 private helpers
- ~2495 LOC total

### Routers (REFACTORED — 7 of 13)
| Router | Before | After | Reduction |
|--------|--------|-------|-----------|
| routers/orders.py | 654 | 178 | -73% |
| routers/payments.py | 268 | 68 | -75% |
| routers/cart.py | 529 | 175 | -67% |
| routers/combos.py | 426 | 194 | -55% |
| routers/products.py | 264 | 176 | -33% |
| routers/inventory.py | 112 | 86 | -23% |
| routers/pricing_settings.py | 128 | 100 | -22% |

Total router LOC: ~4000 → 2149 (46% reduction).

### Routers (UNTOUCHED — 4 of 13)
- `routers/auth.py` — never in scope
- `routers/admin.py` — never in scope
- `routers/age_verification.py` — never in scope
- `routers/payment_settings.py` — never in scope

### Bug Fixes Preserved (from add-stock-tests)
- Race condition in `create_order` ($gte guard + manual rollback) — preserved in `services/orders_helpers.py` (line 51: `{"_id": p["id"], "stock": {"$gte": p["quantity_to_decrement"]}}`; lines 54-66: manual rollback loop).
- Indentation in `update_order_status` (rollback inside cancel/refund if) — preserved in `services/orders.py` (lines 175-184: stock restore inside `if new_status in (CANCELLED, REFUNDED)` block).

## Synced Specs

The new `service-layer` capability is now in the main specs folder:
- `openspec/specs/service-layer/spec.md` (synced from the delta spec at `openspec/changes/service-layer/specs/service-layer/spec.md`)

Both files are 238 lines / 12495 bytes — byte-identical copy. Future SDD changes can now reference this capability directly.

## Stale Checkbox Reconciliation (exceptional repair)

At archive time, 32 of 41 task items in `openspec/changes/service-layer/tasks.md` were still marked `- [ ]`. The sdd-archive skill policy (`sdd-archive/SKILL.md`) requires the archived tasks artifact to have NO stale unchecked implementation tasks. Per the skill's exception path, the orchestrator's launch prompt stated: "All 10 PRs of the change are merged to main. The final `sdd-verify` reported PASS." This is the explicit orchestrator instruction to reconcile, and the verify-report on disk plus apply-progress observation #218 prove every unchecked task is complete.

Action taken: mechanically marked all 32 `- [ ]` task items as `- [x]`. No other content in `tasks.md` was modified. Final state: 41/41 task items checked. This repair is the sole reason `tasks.md` was touched during archive; it is a documentation-only operation and the skill permits it with this exact audit trail entry.

## Process Learnings (for future changes)

1. **Slicing discipline matters**: The 4-slice design (Inventory → Pricing → Cart → Orders) was correct, but the gap-closure (PRs #5a, #5b-1/2a/2b) revealed that the design's "8 services" list needed to be split into individual slice tasks more explicitly. The `verify` phase caught what the `tasks` phase missed.

2. **Backward-compat shims are not free**: PR #1b kept `check_and_create_alert` and `get_alerts_collection` as shims in `routers/inventory.py` so `routers/orders.py` didn't need touching. This was a deliberate trade-off (clean slice vs. cascade). It worked, but it left dead code in inventory.py that needed cleanup in PR #4. Future changes should plan the shim lifecycle upfront.

3. **The auto-split rule is the right call**: The user established "auto-split if over 400 LOC." PR #1 (the original InventoryService + exceptions combined) hit 418 LOC. Splitting it into #1a (exceptions) + #1b (InventoryService) was correct — the user requested this when the verify showed the overrun. The exceptions tree was the larger file (217 LOC) and made more sense as its own PR.

4. **`sdd-verify` caught a planning failure**: The original design listed 8 services (including products, combos), but the tasks.md Phase 2/3 only refactored the PRICING parts of products/combos, not the full CRUD. The verify surfaced this gap. Future changes should have task entries that say "extract full X service" not just "refactor pricing call sites in X router."

5. **The MANUAL_SMOKE.md was a useful spec requirement**: Having to list 6+ endpoints with curl examples forced us to think about what "API 1:1 byte-identical" means in practice. Without it, the API preservation would have been implicit.

## Follow-Up Changes (deferred from this change)

These were explicitly out-of-scope and should be the next changes:

1. **`normalize-error-responses`** — unificar códigos de error (e.g., 409 consistent for stock, structured error bodies). Highest priority follow-up per user.
2. **`add-tests-for-uncovered-modules`** — payments, combos (full coverage), pricing dynamic, emails, auth.
3. **`.env.example`** — document required env vars for new developers.
4. **CI pipeline** — GitHub Actions to run tests on PR.
5. **Future: refactor the 4 out-of-scope routers** (auth, admin, age_verification, payment_settings) into services.

## Engram References

- `sdd/service-layer/explore` (obs #209)
- `sdd/service-layer/proposal` (obs #213)
- `sdd/service-layer/spec` (obs #214)
- `sdd/service-layer/design` (obs #215)
- `sdd/service-layer/tasks` (obs #216)
- `sdd/service-layer/apply-progress` (obs #218)
- `sdd/service-layer/verify-report` (obs #221)
- `webmarket/service-layer-scope` (decision, obs #211)
- `webmarket/service-layer-api-contract` (decision, obs #212)
- `webmarket/current-architecture` (obs #210)
- `webmarket/pending-tasks` (obs #174, updated to mark service-layer as completed)
- `sdd/service-layer/archive-report` (this report, new observation)
