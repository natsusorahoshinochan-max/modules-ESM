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

## Executor repair evidence

- Controller rejected executor revision
  `74c4161011741778bf92ac0dc9b0a8169328a65a` after the cumulative routine
  gate returned `2 failed, 1221 passed, 52 deselected`; retained failure:
  `verification-results/routine/20260730T015429.530516Z-74646-bace01893cd3593e`.
- `/diagnosing-bugs` isolated an existing cross-ticket race in the shared
  prompt-authoring test helper: `PreparedPromptOperation.start()` called
  `start_background()` and immediately read projection/events without
  waiting for the durable Run terminal. Full-suite scheduling could therefore
  expose `running` even though the same cases usually completed inside the
  fast-run grace period.
- Deterministic TDD RED blocks a real prompt Node with `threading.Event`,
  fixes `FAST_RUN_COMPLETION_GRACE_SECONDS` to zero, and proves the old helper
  returns a non-terminal projection. The fixed helper waits through
  `wait_for_public_events()` until the ledger reports terminal; it adds no
  polling sleep and preserves the real succeeded/failed outcome. Reviewer
  differential verification produced `10/10 RED` for the old helper and
  `10/10 GREEN` for the repair.
- Repair commits: `ec5d3b5` and `5847fb6`. Clean repair implementation SHA:
  `5847fb6a96d8cc6268ddc38abd81055905f03492`.
- Prompt-authoring focused regression:
  `uv run --no-sync pytest -q tests/test_prompt_authoring_prompt_v2.py
  tests/test_prompt_authoring_behavior_v2.py
  tests/test_prompt_stochastic_cache_v2.py` → `46 passed`.
- Structure-comparison focused regression remained green:
  `22 passed, 36 deselected`.
- Tickets 01–26 v2 joint regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `535 passed`.
- Full routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1224 passed, 52 deselected`; retained result
  `verification-results/routine/20260730T021340.074396Z-92565-d5c61a1943a88482`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260730T021340.074690Z-92564-3374fb1c9b2e8ad5`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260730T021340.074396Z-92566-1244ef0a2c2bad79`.
- Final `/code-review` Standards and Spec axes both report PASS with zero
  CRITICAL/HIGH findings. The repair diff under `core/` is empty, Ticket 27
  remains untouched, and Ticket 26 remains `awaiting-controller`.

## Executor second repair evidence

- Controller rejected executor revision
  `5cd16a28321b5c8ffc4538698b4087b4048b3b3e` after the cumulative routine
  gate returned `1 failed, 1223 passed, 52 deselected`; retained failure:
  `verification-results/routine/20260730T022224.515714Z-5477-fe311ed83741ce7a`.
  The failure was
  `test_public_import_transform_export_keeps_artifacts_run_bound`, whose
  immediate projection read observed the asynchronous `202 Accepted` Run in
  `running`.
- `/diagnosing-bugs` showed this was the same protocol-level scheduling race,
  not a structure-transform failure. A public `start_run` receipt admits
  background work; `FAST_RUN_COMPLETION_GRACE_SECONDS` is only a best-effort
  fast-path and cannot be used as a terminal contract.
- Deterministic TDD RED sets the fast-run grace to zero, blocks a real Run
  behind `threading.Event`, and proves the shared waiter does not return while
  the projection is still `running`. The repair adds
  `tests/fixtures/public_v2.py`: direct-service and TestClient journeys wait
  for the durable ledger terminal without polling sleeps, while the installed
  network journey waits through the validated public Run WebSocket and checks
  terminal-event/projection agreement.
- The shared contract replaces immediate projection reads across structure
  transform, prompt authoring, scoring, result Cache, cancellation/derivation,
  CTK, Run execution, and installed-package journeys. The earlier prompt
  helper now reuses the same service-level terminal wait. Deliberate reads of
  `running`, post-shutdown projections, and restart-reconciliation projections
  remain direct because their synchronization contract is different.
- Second repair commit: `ecd4670`. Clean implementation SHA under final
  verification:
  `ecd467069a87e74f279d2db258947eae604ea847`.
- Prompt-authoring focused regression:
  `uv run --no-sync pytest -q tests/test_prompt_authoring_prompt_v2.py
  tests/test_prompt_authoring_behavior_v2.py
  tests/test_prompt_stochastic_cache_v2.py` → `46 passed`.
- Structure-comparison focused regression remained green:
  `22 passed, 36 deselected`.
- Tickets 01–26 v2 joint regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `536 passed`.
- Full routine gate passed twice at the same clean implementation SHA:
  `1225 passed, 52 deselected` in each run; retained results:
  `verification-results/routine/20260730T025323.823229Z-30336-2bca7b717ce9916b`
  and
  `verification-results/routine/20260730T025836.927518Z-38777-04c2be465efc38a9`.
- Deterministic acceptance:
  `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260730T030353.755757Z-46603-1494fb24e6c6fa06`.
- Installed artifact:
  `3 passed`; retained result
  `verification-results/installed-package/20260730T030503.435499Z-47402-ea98ae1e394b5bd0`.
  All four retained final-gate records report
  `project_revision=ecd467069a87e74f279d2db258947eae604ea847` and
  `project_dirty=false`.
- The second repair diff under `core/` is empty, Ticket 27 remains untouched,
  and Ticket 26 remains `awaiting-controller`.
- Final `/code-review` Standards and Spec re-reviews both report PASS with
  zero CRITICAL/HIGH findings. The Spec reviewer independently confirmed both
  clean routine records and the clean deterministic/installed evidence before
  closing its earlier evidence-completeness finding.
