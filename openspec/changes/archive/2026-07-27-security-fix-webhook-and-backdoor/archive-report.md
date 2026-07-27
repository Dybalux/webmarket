# Archive Report: security-fix-webhook-and-backdoor

- **Change**: `security-fix-webhook-and-backdoor`
- **Archived**: 2026-07-27
- **Archived to**: `openspec/changes/archive/2026-07-27-security-fix-webhook-and-backdoor/`
- **Archive mode**: file-based (openspec convention), maintainer-approved
- **Status**: archived clean — all gates passed

## Intent Recap

Fixed two CRITICAL findings from the 2026-06-15 security audit:

1. **F-001** — MercadoPago webhook signature validation was non-blocking; forged webhooks could alter order state. Now `_validate_signature` raises `ForbiddenError` (403 RFC 9457) on missing/malformed/invalid signatures, and `process_webhook` explicitly re-raises it past its catch-all `except Exception`.
2. **F-003** — Dead-code `authenticate_user` in `security.py` contained hardcoded admin credentials (`admin@example.com` / `123456`). Function deleted (28 lines), `UserLogin` import cleaned up.

## Gate Status at Archive Time

| Gate | Result | Evidence |
|------|--------|----------|
| Task completion (15/15) | ✅ pass | `tasks.md` — all implementation tasks `[x]`, no stale checkboxes |
| Verification | ✅ pass | `verify-report.md`: verdict `pass`, 0 blockers, 0 critical, 2/2 requirements, 8/8 scenarios, 109/109 tests green (`pytest tests/ -v --tb=short`, exit 0), build import check exit 0 |
| Native review | ✅ approved | `review-ledger.md`: lineage `review-1e33d61ba4f8d5ed`, state `approved`, `gates: post-apply: allow`, 0 BLOCKER / 0 CRITICAL (9 WARNING / 6 SUGGESTION, informational), correction budget untouched |
| CRITICAL verify issues | none | per strict-vs-OpenSpec archive policy, would have blocked |

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| `service-layer` | Updated | 2 requirements ADDED, 0 modified, 0 removed, 0 renamed |

Main spec `openspec/specs/service-layer/spec.md`:

- ADDED **"Webhook Signature Validation MUST Be Blocking"** (5 scenarios: valid signature, invalid signature, missing signature in production, missing secret in production, catch-all does not swallow ForbiddenError).
- ADDED **"Dead-Code Backdoor MUST Be Removed"** (3 scenarios: function removed, no router imports, existing tests independent).
- Added a merged-delta provenance note at the top of the file, consistent with the existing `normalize-error-responses` supersession-note pattern.
- All pre-existing requirements from the archived `service-layer` change were preserved untouched. The delta contained no MODIFIED/REMOVED/RENAMED sections, so the merge was purely additive and non-destructive.

## Archive Contents

- `proposal.md` ✅
- `specs/service-layer/spec.md` (delta) ✅
- `design.md` ✅
- `tasks.md` ✅ (15/15 tasks complete)
- `verify-report.md` ✅ (with `gentle-ai.verify-result/v1` YAML envelope at lines 1–14 preserved intact)
- `review-ledger.md` ✅ (`gentle-ai.review-ledger/v1` envelope preserved intact)

## Implementation & Merge State

- Code already merged to `dev`: PR #31 (`e168fdd` — config + blocking fix + backdoor removal) and PR #32 (`66decfe` — webhook signature test coverage).
- Total changed lines: 406 (362 additions + 44 deletions); 400-line budget exceeded by 6 (1.5%) — user accepted `size:exception` during verify.
- Work-unit commits: `40664f5` (config), `b0d4954` (fix), `6d2f03b` (refactor), `a0d400e` (tests).

## Traceability

- Engram observations referenced by artifacts: #264 (audit), #267/#268 (design inputs), obs-0fd556c8956eb008, #273 (apply progress).
- Review receipt: `.git/gentle-ai/review-transactions/v2/review-1e33d61ba4f8d5ed/review-receipt.json`.
- Source audit: `openspec/audits/security-audit-2026-06-15.md` (F-001, F-003).

## Intentional Deviations / Notes

- **File-based archive without native dispatcher**: the native SDD dispatcher stays red for this legacy change due to a local tooling limitation (it expects receipt mirror files this binary cannot materialize). The maintainer explicitly approved proceeding with the file-based archive. Recorded here as required for any non-standard archive path.
- **No stale-checkbox reconciliation needed**: all tasks were genuinely marked complete by `sdd-apply`.

## Warnings Carried Forward (non-blocking, from verify + review)

- Pre-existing: `process_webhook` catch-all `except Exception` still logs-and-swallows non-`ForbiddenError` failures (returns 200 to MercadoPago on downstream errors; MP won't retry). Out of scope here; recommended for a future service-layer hardening PR.
- Review follow-up pertaining to this change's docs: two relative source links in `design.md:10` resolve one directory too high (`../proposal.md`, `../specs/service-layer/spec.md`). Left unmodified — the archive is an audit trail and archived changes are never edited after the fact.

## Open Questions (deferred)

- Whether `MERCADOPAGO_ALLOW_UNSIGNED_WEBHOOKS` should default to `true` in development (MP test-panel sends unsigned webhooks). Safe default `false` shipped; to be revisited after the audit's 6-PR remediation plan completes.

## Source of Truth Updated

- `openspec/specs/service-layer/spec.md` now reflects blocking webhook signature validation and the absence of `authenticate_user`.

## SDD Cycle Complete

The change has been fully planned, implemented, verified, reviewed, and archived. Ready for the next change (recommended: the next PR in the audit's remediation plan — F-002 Decimal refactor or F-004→F-010 HIGH findings).
