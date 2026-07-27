schema: gentle-ai.review-ledger/v1
lineage_id: review-1e33d61ba4f8d5ed
target_identity: sha256:1e33d61ba4f8d5edf4010acb9916911abb8f358886794abcd519a35815e4ca0c
state: approved
tier: high
correction_budget: 200
corrections_used: 0
store_revision: sha256:99a3d2b065b44a7068a7012d79c1002095b14c52be6e4d93cc2d2d3a1ba4a456
receipt_path: .git/gentle-ai/review-transactions/v2/review-1e33d61ba4f8d5ed/review-receipt.json
verification_evidence: sha256:b8110b51afad38a6887061a2a998236765c1f07b530927dbb7c3d5810924ea05
gates:
  post-apply: allow
lenses:
  - lens: review-risk
    order: 0
    subject_hash: sha256:a7a0585a3b8ad54028ac3a3c64e412d5d7a69e9f12593e9659d229db07f3ed33
    admission_decision: completed
  - lens: review-resilience
    order: 1
    subject_hash: sha256:58f392d228b08c37dfb312aaf177d5b2ff34b1098decffdbf1e8a748a9d7ac0c
    admission_decision: completed
  - lens: review-readability
    order: 2
    subject_hash: sha256:252c89ca4beb1317515b7baf28be5126239c60461b56481aba4320f169db9c88
    admission_decision: completed
  - lens: review-reliability
    order: 3
    subject_hash: sha256:bc0fdb3ed2c9b72c3b26baf09f88e29d91b593108ae6c6b9a78043d255ced9d7
    admission_decision: completed
findings:
  - id: RISK-1
    severity: WARNING
    location: openspec/audits/security-audit-2026-06-15.md:258
    claim: Audit doc commits the literal MongoDB dev root password value (also present in docker-compose.yaml at HEAD per F-013); duplicate committed copy makes future scrubbing/rotation harder.
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "Line 258: 'MONGO_INITDB_ROOT_PASSWORD=miContraseñaSecreta'; repeated at lines 249 and 472."
  - id: RISK-2
    severity: WARNING
    location: openspec/config.yaml:12
    claim: Refreshed config.yaml claims 'Deployment: Railway' while audit F-019 claims the project migrated off Railway on 2026-06-13. Cross-lens adjudication (review-reliability) found an active railway.toml at repo root today, corroborating config.yaml; audit F-019 is the dated claim.
    evidence_class: deterministic
    causal_disposition: unknown
    proof_refs:
      - "config.yaml:3 'Re-initialized: 2026-07-26'; config.yaml:12 'Deployment: Railway (Dockerfile, python 3.13-alpine, gunicorn)'; audit lines 345-357 (F-019); railway.toml at repo root."
  - id: RISK-3
    severity: SUGGESTION
    location: openspec/changes/service-layer/design.md:443
    claim: Archived service-layer design documents the webhook contract as non-blocking (HMAC-SHA256 non-blocking in testing, _validate_signature -> bool); superseded by the merged security fix (ForbiddenError -> 403). A future reader could copy the stale contract.
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "design.md:443 'non-blocking in testing'; :119 'always returns 200'; :121 '_validate_signature(request, secret) -> bool'."
  - id: RISK-4
    severity: SUGGESTION
    location: openspec/audits/security-audit-2026-06-15.md:373
    claim: F-021 embeds an absolute local machine path (developer username and directory layout) in a doc destined for push. Minor information disclosure; no secret values leaked.
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "Line 373: '/home/dybalux/Escritorio_Dev/webmarket/.env'; line 375 ls -la output."
  - id: RES-1
    severity: WARNING
    location: openspec/changes/service-layer/design.md:119
    claim: Design mandates the payment webhook always returns 200 on downstream failures (MercadoPago unreachable, Mongo errors), so MercadoPago never retries and payment state transitions are silently lost (orders stuck PENDING). Documented as pre-existing debt in the security-fix verify-report.
    evidence_class: deterministic
    causal_disposition: pre-existing
    proof_refs:
      - "design.md:119 'logs errors, always returns 200'; security-fix verify-report lines 101-105 (deferred, minimal blast radius)."
  - id: RES-2
    severity: WARNING
    location: openspec/config.yaml:12
    claim: Same Railway deployment-claim divergence between refreshed config.yaml and audit F-019. CI claims in config.yaml:12 verified true against .github/workflows (ci.yml, cd.yml). Causality unknown; adjudicated in config.yaml's favor by railway.toml evidence.
    evidence_class: deterministic
    causal_disposition: unknown
    proof_refs:
      - "config.yaml:3 and :12 vs security-audit-2026-06-15.md:345-357 (F-019)."
  - id: RES-3
    severity: SUGGESTION
    location: openspec/changes/service-layer/design.md:442
    claim: Archived design prescribes non-blocking webhook signature validation — the exact CRITICAL finding (F-001) later corrected by the merged security fix; stale contract contradicts implemented blocking behavior.
    evidence_class: deterministic
    causal_disposition: pre-existing
    proof_refs:
      - "design.md:442 'non-blocking in testing'; :121 '_validate_signature -> bool' vs audit F-001 and security-fix spec."
  - id: RES-4
    severity: SUGGESTION
    location: openspec/changes/service-layer/specs/service-layer/spec.md:9
    claim: Spec mandates 'MongoDB remains on M0 (no transactions)' with no compensation/idempotency behavior for mid-orchestration failures in create_order (order persisted, later step fails; retry without idempotency key risks duplicates — audit F-022, pre-existing).
    evidence_class: deterministic
    causal_disposition: pre-existing
    proof_refs:
      - "spec.md:9; design.md sequence lines 314-367 (no failure branch after insert); audit F-022 lines 380-388."
  - id: READ-1
    severity: WARNING
    location: openspec/config.yaml:12
    claim: Same Railway deployment-claim divergence (cross-lens duplicate of RISK-2/RES-2, kept for lens traceability). Resolution: railway.toml corroborates config.yaml; audit F-019/F-025 wording is dated.
    evidence_class: deterministic
    causal_disposition: unknown
    proof_refs:
      - "config.yaml:3, :12 vs security-audit-2026-06-15.md:350, :356."
  - id: READ-2
    severity: WARNING
    location: openspec/audits/security-audit-2026-06-15.md:6
    claim: Executive summary severity tally is arithmetically false: claims 26 (3/8/9/6/3) which sums to 29; actual per-finding labels give 3 CRITICAL / 7 HIGH / 8 MEDIUM / 5 LOW / 3 INFO = 26. Total is correct; distribution used for triage is wrong on three buckets.
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "Line 6: '26 (CRITICAL: 3, HIGH: 8, MEDIUM: 9, LOW: 6, INFO: 3)' = 29; counted labels in body: 3/7/8/5/3 = 26. Corroborated independently by REL-1."
  - id: READ-3
    severity: WARNING
    location: openspec/changes/service-layer/tasks.md:74
    claim: tasks.md marks four apply-progress.md updates complete with verification 'file exists', and the spec mandates the artifact, but the service-layer change folder contains no apply-progress.md; the checked-off verification claim is false in the final archived state.
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "tasks.md:74-75 marked [x]; change-folder listing contains no apply-progress.md."
  - id: READ-4
    severity: WARNING
    location: openspec/changes/service-layer/archive-report.md:35
    claim: Router-count denominator unreconciled: docs say '13 routers' but archive-report accounts for 7 refactored + 4 untouched = 11; verify-report enumerates 11 and the merged repo has exactly 11 router modules. The historical record misstates its own scope.
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "archive-report.md:35 '7 of 13' + :48 '4 of 13' = 11; on-disk routers/ has 11 modules."
  - id: READ-5
    severity: SUGGESTION
    location: openspec/changes/service-layer/verify-report.md:105
    claim: '75% reduction' claim for refactored routers is arithmetically wrong: 2381 LOC before vs 977 after = ~59%, not 75%. Per-router figures are each correct; the aggregate is a slip.
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "verify-report.md:105; archive-report.md Before/After sums 2381->977."
  - id: READ-6
    severity: SUGGESTION
    location: openspec/changes/security-fix-webhook-and-backdoor/design.md:10
    claim: Two of three relative source links are broken ('../proposal.md' and '../specs/service-layer/spec.md' resolve one directory too high; targets are siblings of design.md).
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "design.md:10 Sources line; change-folder listing shows proposal.md and specs/ are siblings."
  - id: REL-1
    severity: WARNING
    location: openspec/audits/security-audit-2026-06-15.md:6
    claim: Duplicate corroboration of READ-2 by review-reliability with explicit line-census of severity headers (CRITICAL 3, HIGH 7, MEDIUM 8, LOW 5, INFO 3).
    evidence_class: deterministic
    causal_disposition: introduced
    proof_refs:
      - "Severity headers counted at lines 22..433: 3/7/8/5/3 = 26."
follow_ups:
  - Redact the literal Mongo dev password from the audit doc and rotate per F-013 recommendation.
  - Treat audit F-019/F-025 deployment wording as dated; config.yaml deployment claim stands (railway.toml active).
  - Fix the audit executive-summary severity tally (3/7/8/5/3) before publishing the doc.
  - Add a 'superseded by security-fix-webhook-and-backdoor' note to service-layer design webhook sections.
  - Replace the absolute local path in audit F-021 with a repo-relative path.
  - Reconcile service-layer historical counts (routers 11 not 13; 59% not 75%; apply-progress.md absence) or annotate as historical record.
  - Fix the two broken relative links in security-fix design.md:10.
---

# Review Ledger: security-fix-webhook-and-backdoor

Bounded ordinary review over the change's documentation candidate (12 added SDD docs + modified openspec/config.yaml; 2593 lines, tier high, 4R lenses).

- **Lineage**: review-1e33d61ba4f8d5ed — state `approved`
- **Receipt**: .git/gentle-ai/review-transactions/v2/review-1e33d61ba4f8d5ed/review-receipt.json
- **Lenses**: review-risk, review-resilience, review-readability, review-reliability — all `completed`
- **Findings**: 0 BLOCKER / 0 CRITICAL, 9 WARNING, 6 SUGGESTION (warnings/suggestions are informational; none block)
- **Verification evidence**: full suite green 109/109 (`pytest tests/ -v --tb=short`, exit 0); build import check exit 0
- **Gate**: post-apply = allow
- **Correction transactions**: none required (no blockers); budget 200 untouched
