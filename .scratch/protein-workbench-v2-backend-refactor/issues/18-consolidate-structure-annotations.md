# 18 — Consolidate structure annotations

**What to build:** A Workflow can compute secondary structure, SASA, and secondary-structure agreement through one `structure_annotation` Module Package with shared residue mapping, truthful binary readiness, and formally typed annotation or scoring outputs.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** awaiting-controller

- [x] DSSP computation, secondary-structure extraction, SASA calculation, and secondary-structure agreement each have one v2 Node Definition under one package registration.
- [x] Duplicate DSSP invocation, structure parsing, residue correspondence, and annotation conversion logic is consolidated behind package-local implementation or adapters.
- [x] The DSSP binary identity and runtime path belong to the Binding and trusted Environment Configuration, with startup Availability and per-Run Readiness instead of Workflow path parameters.
- [x] Annotation outputs preserve exact residue layout, chain boundaries, missing residues, and nullable values and fail closed on an irreconcilable correspondence.
- [x] ESM-3 SS8 legal symbols `GHITEBSC` are preserved, unsupported DSSP `-` maps to `C`, and absent values remain `_`; no implicit SS8-to-SS3 conversion is introduced.
- [x] Secondary-structure agreement is a declared Metric/Method/Context Observation with validated range, direction, multiplicity, and subject identity rather than a free-form score.
- [x] Readiness failure occurs before binary invocation or Cache lookup, while actual DSSP execution creates truthful Operation and Engine Invocation evidence.
- [x] Regression fixtures cover the accepted layout-shift defect, multi-chain structures, missing residues, malformed DSSP output, and post-processing failure.
- [x] The package passes CTK, deterministic public acceptance, and installed discovery without Core provider maps.

## Executor evidence

This records executor completion only. Ticket 19 must not start until the
Controller independently runs the cumulative Tickets 01–18 gate and accepts
this state. Any joint-test regression must be returned to this Ticket 18
executor for repair before that next Ticket starts.

- Fixed implementation/review base:
  `4221bc203b1be9c5fd466f9515e5d10a11b7ae52`.
- Implementation and review-fix commits: `70f866c`, `86fd706`, and `54617f4`.
- Joint Tickets 01–18 v2 regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `419 passed`.
- Focused structure-annotation and legacy-adapter regression:
  `uv run --no-sync pytest -q tests/test_structure_annotation_v2.py
  tests/test_port_types_v2.py tests/test_protein_prompt.py
  tests/test_scoring.py tests/test_provider_evidence.py
  tests/test_contained_storage.py` → `172 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1101 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T144121.580849Z-95037-a2c8f672fccbe08b`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T144346.741434Z-95842-5b65d4ea25d3abd4`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T144434.492712Z-95963-e82523d75c97e288`.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and the
  zero-Core-diff check passed at clean implementation HEAD `54617f4`.
- Parallel `/code-review` Standards and Spec reviewers drove repairs for
  exact DSSP version parsing, truthful startup Availability, residue-name
  reconciliation, absent-symbol handling, explicit pairwise reference
  identity, and consolidation of legacy modules behind package-local
  adapters. Both final review axes returned `APPROVE` at `54617f4`.
