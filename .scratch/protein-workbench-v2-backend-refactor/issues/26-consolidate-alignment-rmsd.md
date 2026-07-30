# 26 — Consolidate alignment and RMSD

**What to build:** A Workflow can align one structure pair or corresponding Candidate collections and compute RMSD from explicit reproducible correspondence evidence through one `structure_comparison` Module Package.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** awaiting-controller

- [x] Single alignment, pairwise collection alignment, and RMSD each have one v2 Node Definition in a single package registration.
- [x] Alignment output is a versioned nominal value that records exact subject/reference Candidate identities and content digests, residue/atom correspondence, transformation, normalization inputs, and method identity.
- [x] Input role semantics remain explicit regardless of the underlying library's reference/mobile call ordering.
- [x] Pairwise collection alignment defines its accepted cardinality and pairing source rather than relying on collection order, free-form Candidate IDs, or lineage guessing.
- [x] RMSD is emitted as a declared pairwise Metric/Method/Context Observation and cannot accept a mutable `candidate_id` or anonymous alignment.
- [x] The package records a composite Operation separately from any nested alignment engine Invocations and represents their true parent-child relationship.
- [x] Incomplete correspondence, incompatible structures, empty selections, invalid transformations, non-finite values, and conflicting identities fail before output or Cache publication.
- [x] Deterministic fixtures prove exact correspondence evidence, role orientation, multi-Candidate behavior, Cache replay, and failure isolation.
- [x] All Nodes pass CTK and installed discovery without duplicate alignment adapters, Definitions, or Core scoring logic.

## Executor evidence

- Starting Controller gate:
  `a3dfa37cbf091252e9affc3758043964dfcdf700`.
- TDD RED began with
  `tests/test_structure_comparison_v2.py` failing because
  `modules.structure_comparison` did not exist. Later RED cases proved that
  arbitrary Method digests, omitted nominal RMSD/coverage, high-ambiguity
  tmtools fallback, and bounded multi-correspondence SVD selection were not
  represented by exact validation and truthful Invocation evidence.
- Implementation commits: `e99f72d`, `c624c8a`, `7058bbc`, and `e44e6b2`.
  Clean implementation SHA under final verification:
  `e44e6b2badc77f7cc4ff3e2d9ab0a23dce841f0a`.
- Focused structure-comparison and legacy alignment-evidence regression:
  `uv run --no-sync pytest -q tests/test_structure_comparison_v2.py
  tests/test_provider_evidence.py -k 'structure_comparison or
  ambiguous_alignment or pairwise_tiebreak_failure or
  svd_postprocessing_failure'` → `22 passed, 36 deselected`.
- Tickets 01–26 v2 joint regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `534 passed`.
- Full routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1223 passed, 52 deselected`; retained result
  `verification-results/routine/20260730T014419.907339Z-62862-2309975be503dac0`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260730T014419.907172Z-62864-d34f24a62585d089`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260730T014419.907093Z-62863-b9cf4c292b96f500`.
- CTK coverage is included in the focused and routine gates and exercises all
  three Nodes, four Bindings, and both nominal Port Types.
- `/code-review` initially found HIGH gaps in tmtools fallback provenance and
  exact Method-digest validation. Those were closed by separate
  `sequence_alignment`, `correspondence_tiebreak`,
  `bounded_correspondence_selection`, and `rigid_superposition` Invocations
  with exact dependency identity and validated parent relationships. A later
  installed-package failure exposed Biopython `1.85` versus unconstrained
  `1.87` catalog drift; exact dependency pins closed it. Final Standards and
  Spec re-reviews report zero CRITICAL/HIGH findings.
- `git diff --check
  a3dfa37cbf091252e9affc3758043964dfcdf700..HEAD` passes. The Ticket 26
  diff under `core/` is empty; this ticket adds no Core scoring logic.
- Ticket 27 was not started. Ticket 26 remains `awaiting-controller` until
  the Controller independently runs the cumulative multi-ticket gate.
