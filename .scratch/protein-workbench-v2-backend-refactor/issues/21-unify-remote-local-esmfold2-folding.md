# 21 — Unify remote and local ESMFold2 folding

**What to build:** A Workflow can fold a protein sequence with an explicitly selected remote or local ESMFold2 Binding of one shared folding Node Type and receive complete structure Candidates plus canonical `[0,100]` pLDDT Observations.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** completed

- [x] One folding Node Definition owns the cross-Binding scientific inputs, outputs, and parameters; remote and local ESMFold2 are explicit Bindings rather than separate scientific Node Types.
- [x] Each Binding fixes its execution route, Method, model/source identity, adapter/implementation identity, Readiness, determinism, and cacheability without a mutable `model_name`.
- [x] Credentials, endpoint, local model path, device, and runtime settings are injected through trusted Environment Configuration and do not enter Workflow parameters.
- [x] Neither Binding is selected or substituted by Availability; unavailable local execution leaves the remote Binding discoverable and vice versa.
- [x] ESMFold2 native `[0,1]` per-residue pLDDT is statically multiplied by 100 and exposed as `structure.plddt.per_residue`; `structure.plddt.mean_residue` is the equal-weight mean over valid protein residues only.
- [x] Padding, chain breaks, non-protein tokens, and NaN are excluded from the mean; pTM remains `[0,1]`, PAE remains in angstroms, and no observed-range scale guessing is used.
- [x] Every sample yields a complete, validated structure Candidate with stable parent/sample/content lineage and exact Produced Observations.
- [x] Readiness precedes Cache, actual folding crosses a declared Engine Invocation seam, and decode or normalization failure cannot publish a successful Candidate.
- [x] Differential provider-native fixtures plus required remote and local gates prove scale, completeness, no fallback, source-bound evidence, and CTK conformance.

## Executor evidence

This records executor completion only. Ticket 22 must not start until the
Controller independently runs the cumulative Tickets 01–21 gate and accepts
this state. Any joint-test regression must be returned to this Ticket 21
executor for repair before that next Ticket starts.

- Fixed implementation/review base:
  `c31027e067ea07f6df637473c4f03e3ab403cdce`.
- Implementation and review-fix commits span `8f2af14` through `b383217`.
- Joint Tickets 01–21 v2 regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `462 passed`.
- Focused folding regression:
  `uv run --no-sync pytest -q tests/test_folding_v2.py` → `13 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1147 passed, 48 deselected`; retained result
  `verification-results/routine/20260729T193259.017124Z-27820-89c89b78647bd8ce`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T193712.310804Z-33326-9820a9dd46b21227`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T193817.567795Z-33900-a525aa4beef2b0b1`.
- Required local source-contract gate:
  `uv run --no-sync python scripts/verify_backend.py
  local-esmfold2-v2-contract` → `5 passed`; retained result
  `verification-results/local-esmfold2-v2-contract/20260729T193859.564145Z-34026-00894fc74a493dce`.
- Required source-bound remote provider gate:
  `PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION=b383217... uv run
  --no-sync python scripts/verify_backend.py remote-esmfold2-v2` →
  `1 passed`; retained result
  `verification-results/remote-esmfold2-v2/20260729T193912.780128Z-34087-0c018a829d81047a`.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and
  the zero-`core/` diff check passed.
- Parallel `/code-review` Standards and Spec reviewers both returned
  `APPROVE` after the source-authoritative PAE upper bound was corrected to
  `31.75` and exercised through both public v2 routes.
- Ticket 22 has not started.

## Controller evidence

Controller independently accepted the final Ticket 21 revision only after all
Tickets 01–21 joint tests and both explicit ESMFold2 gates passed.

- Previous accepted multi-ticket gate:
  `c31027e067ea07f6df637473c4f03e3ab403cdce`.
- Final executor revision under test:
  `891e143ab4c4c2e891b445f9df4e62868080a6d9`.
- Ticket-range `git diff --check` passed and the worktree was clean before
  testing.
- Tickets 01–21 v2 joint regression:
  `uv run --no-sync pytest -q tests/*_v2.py` → `462 passed`.
- Focused folding regression:
  `uv run --no-sync pytest -q tests/test_folding_v2.py` → `13 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1147 passed, 48 deselected`; retained result
  `verification-results/routine/20260729T194408.477525Z-38503-c9a2758f734a18f2`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T194825.177626Z-43980-e08280b89008c511`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T194825.176700Z-43981-7da2dd6b39b1d565`.
- Local source-contract gate:
  `uv run --no-sync python scripts/verify_backend.py
  local-esmfold2-v2-contract` → `5 passed`; retained result
  `verification-results/local-esmfold2-v2-contract/20260729T194825.177167Z-43979-75070462be0c21f8`.
- Required clean-source remote provider gate:
  `PROTEIN_WORKBENCH_APPROVED_SOURCE_REVISION=891e143ab4c4c2e891b445f9df4e62868080a6d9
  uv run --no-sync python scripts/verify_backend.py remote-esmfold2-v2` →
  `1 passed` with complete Biohub folding evidence; retained result
  `verification-results/remote-esmfold2-v2/20260729T194944.157636Z-44735-733029c4a18aa5a6`.

Ticket 22 may start only from the committed Controller gate containing this
evidence.
