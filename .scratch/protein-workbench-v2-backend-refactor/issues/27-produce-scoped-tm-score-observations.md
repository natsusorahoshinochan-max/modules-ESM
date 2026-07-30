# 27 — Produce scoped TM-score Observations

**What to build:** A Workflow can compute single or batch TM-score Observations with standard reference normalization and use separate fixed-reference and per-subject counterpart scopes without cross-matching or ambiguous score IDs.

**Blocked by:** 26 — Consolidate alignment and RMSD.

**Status:** awaiting-controller

- [x] Single and batch TM-score each have one v2 Node Definition in the existing `structure_comparison` package and consume the explicit alignment evidence contract.
- [x] TM-score is a declared pairwise Metric with exact Method, canonical range, direction, context roles, and reference-normalization semantics rather than a caller-provided `score_id`.
- [x] Every Observation identifies the subject Candidate and exact reference Candidate identity/content digest and preserves the alignment and normalization provenance that determined the value.
- [x] Batch output retains one declared source partition and the exact per-subject pairing cardinality needed by compiler capability analysis and selection.
- [x] A fixed canonical reference may match every subject only in its declared objective, while each folded ESM-3 subject matches exactly one distinct paired counterpart in the other objective.
- [x] Collection order, name suffixes, incidental lineage, and first-match behavior cannot determine reference selection.
- [x] Non-finite scores, missing references, duplicate matches, wrong role orientation, conflicting normalization, or undeclared multiplicity fail closed before Score Collection publication.
- [x] Deterministic regressions prove standard reference normalization, the two isolated canonical objective scopes, nested engine evidence, and Cache-stable Observation identities.
- [x] Both Nodes pass CTK, public protocol, and installed-artifact tests without a structure-comparison Core special case.

## Executor evidence

- Starting Controller gate:
  `a9b86cbe49e8d7c2698172748ac54eabeb80e959`.
- TDD RED first proved that the single and batch TM-score Definitions and
  Bindings were absent. Later RED cases exposed incorrect tmtools transform
  orientation, missing paired and fixed-reference batch scopes, accepted
  conflicting reference digests, incomplete evidence provenance, forged
  normalization residue counts, cross-objective compiler ambiguity, and
  partial batch engine entry before a later invalid item was rejected.
- Implementation commits: `3c77386`, `7d9ca7f`, `a6939b6`, and `7154c8d`.
  Clean implementation SHA under final verification:
  `7154c8dda3c4b1fc27f6559558a3881c678fd530`.
- The implementation declares the scalar, dimensionless, higher-is-better
  `structure_comparison.tm_score` Metric with canonical range `[0, 1]` and
  the exact `structure_comparison.tm_score.reference_normalized.method`.
  Single and batch Observations preserve subject/reference identities and
  content digests, alignment evidence and Method, normalization length,
  aligned-atom count, and the declared source partition.
- Fixed-reference alignment accepts only a declared singleton reference and
  many subjects; per-subject scoring accepts only exact typed one-to-one
  pairings. Whole-batch preflight validates every alignment and exact
  Candidate content before any TM engine Invocation, so invalid later items
  cannot partially enter scoring or publish a Score Collection.
- Focused TM-score, structure-comparison, pairwise-scoring, and legacy
  regressions:
  `uv run --no-sync pytest -q tests/test_tm_score_observations_v2.py
  tests/test_structure_comparison_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_standard_tm_score.py tests/test_batch_tm_score.py
  tests/acceptance/test_alignment_tm.py` →
  `66 passed, 1 deselected`.
- Tickets 01–27 v2 joint regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `550 passed`.
- Full routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1239 passed, 52 deselected`; retained result
  `verification-results/routine/20260730T040133.009927Z-94540-4c7beabd85138440`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260730T040641.263373Z-2311-959af1a675a5a6db`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260730T040753.178882Z-2939-4a3ef38d6521c2e3`.
  All three retained records report
  `project_revision=7154c8dda3c4b1fc27f6559558a3881c678fd530` and
  `project_dirty=false`.
- CTK covers all five package Nodes and all eight Bindings. Public protocol
  coverage executes paired batch TM-score through the public Run lifecycle,
  while installed-package coverage verifies the packaged Definitions,
  Metric, Method, and resources.
- `/code-review` initially identified a HIGH exact-normalization gap and
  MEDIUM compiler-isolation and batch-preflight gaps. Exact Candidate PDB
  residue cross-checking, simultaneous dual-objective coverage, and
  whole-batch validation closed them. Final Standards review reports
  `0 CRITICAL / 0 HIGH — PASS`; final Spec review reports
  `PASS — 0 CRITICAL / 0 HIGH / 0 MEDIUM`.
- `compileall`, `uv lock --check`, `uv pip check`, and
  `git diff --check
  a9b86cbe49e8d7c2698172748ac54eabeb80e959...HEAD` pass. The Ticket 27
  diff under `core/` is empty.
- Ticket 28 was not started. Ticket 27 remains `awaiting-controller` until
  the Controller independently runs the cumulative multi-ticket gate.
