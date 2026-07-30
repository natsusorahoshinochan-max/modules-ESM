# 34 — Re-prove deterministic canonical 3GB1

**What to build:** The canonical 3GB1 design Workflow is rewritten as an exact v2 Workflow and, through the installed-backend public protocol, deterministically reproduces its complete scientific intent, ranking, lineage, folding, artifacts, and causally closed execution evidence.

**Blocked by:** 13 — Consolidate protein I/O; 15 — Assemble and update ProteinPrompts; 16 — Make stochastic prompt authoring reproducible; 18 — Consolidate structure annotations; 19 — Migrate remote ESM-3 generation; 21 — Unify remote and local ESMFold2 folding; 24 — Consolidate ProteinMPNN constraints and design; 27 — Produce scoped TM-score Observations; 28 — Preserve partitions in collection operations; 30 — Migrate explicit multi-objective selection.

**Status:** awaiting-controller

- [x] The maintained canonical seed uses v2 schema, exact Node/Binding versions, separate parameters, explicit effective seeds, and a complete reachable Contract Lock.
- [x] Public compilation proves exact Port compatibility, Binding ownership, Produced Observation capabilities, the two objective source scopes, and immutable resolved contract digests before execution.
- [x] Prompt construction preserves the accepted 3GB1 layout, residue edits, masks, insertions, visibility, secondary-structure symbols, and other scientific tracks at the ESM-3 boundary.
- [x] Paired ESM-3 generation produces exactly ten complete sequence/structure Candidate pairs with stable sample identity, counterpart relationship, content, and lineage.
- [x] The fixed-3GB1 TM-score objective uses one exact canonical reference for all subjects, while the paired-ESM3 objective gives every folded subject exactly one distinct exact counterpart; the two scopes cannot cross-match.
- [x] Explicit Utilities and weights select the accepted top three Candidates without raw Metric addition, hidden normalization, missing observations, or order-dependent ties.
- [x] ProteinMPNN produces five complete child sequences for each of the three selected parents, preserving all 3 × 5 parent-child identities and effective randomness.
- [x] Final folding produces fifteen complete structure Candidates and fifteen distinct Run-bound PDB artifacts whose reported hashes and retrieval bytes agree.
- [x] Every Plan Node has one disposition, every started Attempt/Invocation has one terminal, Cache decisions and replay provenance are truthful, and Ledger causal closure is complete.
- [x] Acceptance uses only Catalog Snapshot, Project/Workflow Snapshot, Compile, Start Run, replay/live Events, Run Projection, and Artifact Retrieval from an installed backend; historical v1 bundles or fixed call counts cannot satisfy it.
- [x] Failure variants prove invalid Workflow rejection before provider calls, readiness-before-Cache, downstream-only blocking, unrelated-branch continuation, cancellation, isolation, safe errors, and artifact integrity checks.

## Executor evidence

- Implementation commits: `4f67494`, `5f93e2f`, `319d4aa`.
- `/code-review`: Standards APPROVE and Spec APPROVE at `319d4aa`; no remaining findings.
- Focused canonical installed-backend public-protocol journey: `1 passed`.
- `examples-v2`: `11 passed`; retained at `verification-results/examples-v2/20260730T124724.481729Z-81834-c7500377f826b414`.
- `deterministic-acceptance`: `17 passed, 5 deselected`; retained at `verification-results/deterministic-acceptance/20260730T124221.175187Z-76966-4f866bcb28efbe00`.
- `installed-package`: `4 passed`; retained at `verification-results/installed-package/20260730T124448.901700Z-79603-6a6ae4c86dc064d3`.
- `routine`: `1334 passed, 64 deselected`; retained at `verification-results/routine/20260730T124720.226349Z-81819-a57e44d17040198c`.
- No repository static type-checker or linter command is configured; `git diff --check` passed.
- Executor handoff stops here for the Controller's cumulative Ticket 01–34 joint gate.
