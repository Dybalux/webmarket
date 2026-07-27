# Proposal: Service Layer

## Why

`orders.py` (658 LOC) orchestrates stock, combos, pricing, shipping, alerts, and email inline. `cart.py` duplicates stock validation 4 times. Adding features requires touching routers, tests, and API contract — no place for domain logic without HTTP. A service layer separates business logic from transport, making it testable without the HTTP cycle. **Refactor with API 1:1 preservation**, not redesign.

## What Changes

- Add `services/` with 8 modules + `exceptions.py` + `__init__.py`.
- Modules export **async functions** (not classes), receive `AsyncIOMotorDatabase`, raise **domain exceptions** (e.g., `InsufficientStockError`).
- Routers slim to: parse → call service → translate exceptions to `HTTPException` (identical status/message) → serialize.
- 4 PR slices ≤400 LOC: Inventory → Pricing → Cart → Orders.
- PR #0: delete `routers/orders_backup.py`.

## Impact

| Aspect | Detail |
|--------|--------|
| Routers affected | 13 files (~4000 LOC → ~2000 LOC) |
| New files | 8 service modules + exceptions |
| Tests | 12 files — fixture tweaks only; all must pass |
| User-visible | Zero change. No DB migration |

Risk peaks at Slice 4 (OrderService). Slices 1-3 prove the pattern first.

## Out of Scope

- `repositories/` directory
- `normalize-error-responses` (future change)
- MongoDB transactions upgrade
- New endpoints, features, dependencies
- `models.py` package migration

## Resolved Decisions

1. Services = async functions in modules (not classes).
2. Services receive `AsyncIOMotorDatabase` (cross-collection access for future transactions).
3. Stock: keep `$gte` guard + manual rollback.
4. `orders_backup.py` deleted in PR #0.
5. Routers translate domain exceptions to `HTTPException` with identical shape.

## Non-Goals

No performance optimization. No new tests beyond keeping existing suite green.

## Capabilities

> Contract with sdd-spec. No existing specs.

**New**: None (structural refactor, zero behavior changes).
**Modified**: None (API contract preserved 1:1).

## Approach

Extract business logic from routers into `services/`. Routers become HTTP adapters. Migration ordered by dependency graph (leaf-first): Inventory (0 deps) → Pricing (0 deps) → Cart → Orders.

## Affected Areas

| Area | Impact |
|------|--------|
| `services/` | New (8 modules + exceptions) |
| `routers/` (13 files) | Modified (~4000→~2000 LOC) |
| `routers/orders_backup.py` | Removed |
| `tests/` (12 files) | Modified (fixtures) |
| `README.md` | Modified |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| OrderService breaks order flow | Medium | Last slice; prior slices prove pattern |
| Test fixture changes break unrelated tests | Low | Full suite per slice |
| Slice exceeds 400 LOC | Low | Slices sized 150-350 LOC |

## Rollback Plan

Per-slice: revert merge commit. Overall: revert PRs in reverse order (4→3→2→1).

## Dependencies

- PR #0 must land before Slice 1.
- Slices merge in order (Cart depends on Inventory; Orders depends on all).

## Acceptance Criteria

- [ ] 12 test files pass (fixture tweaks allowed)
- [ ] `curl` produces byte-identical responses (`POST /orders`, `POST /cart/add`, `GET /products`)
- [ ] `services/` has 8 documented modules
- [ ] Routers drop to ~2000 LOC
- [ ] Each slice is separate PR ≤400 LOC, merged in order
