# Archive Report: decimal-refactor

**Archived**: 2026-07-28
**SDD Cycle**: Complete (intentional-with-warnings)

## Summary

SDD change `decimal-refactor` fully implemented across 4 chained PRs (5a→5b→5c→5d), verified with 259 passing tests / 0 failures / 3 expected xfails. 12/12 spec scenarios covered. Verdict: **PASS WITH WARNINGS** (4 partial-compliance items are spec-wording gaps and environment-dependent migration scenarios, not code defects).

## Pending Tasks (stale-checkbox reconciliation)

Per sdd-archive exceptional reconciliation — verify-report evidence proves these are not implementation defects:

- **4.4** — `MANUAL_SMOKE.md` (documentation runbook supplement, not behavioral requirement)
- **4.6** — Staging validation (requires live staging MongoDB instance — environment dependency)

Both are tracked as follow-up work, not blocking archive.

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| monetary-precision | Already at destination | New capability — spec at `openspec/specs/monetary-precision/spec.md`. No delta specs in change folder (spec created directly as main spec). |

## Archive Contents

```
openspec/changes/archive/2026-07-28-decimal-refactor/
├── archive-report.md       ← this file
├── design.md               ← from sdd-design (6 ADRs, data flow, testing strategy)
├── proposal.md             ← from sdd-propose (scope, approach, risks, chained PR strategy)
├── tasks.md                ← from sdd-tasks / sdd-apply (25/27 complete, 2 external pending)
└── verify-report.md        ← from sdd-verify (PASS WITH WARNINGS, 259 tests, 5 reqs, 12 scenarios)
```

## Source of Truth

- `openspec/specs/monetary-precision/spec.md` — main spec reflecting the new capability (already in place)
- `openspec/changes/archive/2026-07-28-decimal-refactor/` — complete audit trail

## SDD Cycle Status

✅ **Complete** with follow-up items:
1. Spec wording corrections for scenarios 2.3 (fraction semantics) and 4.3 (precision coercion)
2. Create `MANUAL_SMOKE.md`
3. Run migration script on staging (task 4.6)
