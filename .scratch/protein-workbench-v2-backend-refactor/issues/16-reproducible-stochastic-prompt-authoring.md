# 16 — Make stochastic prompt authoring reproducible

**What to build:** A Workflow author can randomly mask or insert masked residues while obtaining explicit effective randomness, stable replay semantics, and residue-aligned prompt tracks suitable for deterministic canonical acceptance.

**Blocked by:** 14 — Consolidate residue layout and track editing.

**Status:** awaiting-controller

- [x] Random masking and masked insertion are registered as `prompt_authoring` Nodes with exact input/output Port contracts and no process-global random state.
- [x] Every execution resolves and records an effective seed and all result-affecting random parameters before computing Result Identity.
- [x] Repeating exact inputs and effective randomness produces byte-equivalent canonical outputs; changing the seed or any stochastic parameter changes Result Identity.
- [x] Uncontrolled randomness or an unresolvable effective seed disables cross-Run caching rather than producing an incomplete Cache key.
- [x] Masking changes only the declared track positions and preserves layout length, chain boundaries, nullable values, and untouched tracks.
- [x] Insertion updates layout, residue maps, and every affected track consistently and rejects impossible counts, positions, or layout constraints.
- [x] Fixtures cover zero/full masks, repeated positions, chain boundaries, inserted masked sequence and secondary-structure tracks, and stable replay after Cache materialization.
- [x] The canonical 3GB1 masking and insertion intent is captured as an ordinary regression rather than by relying on historical random call order.
- [x] Both Nodes pass the shared CTK and public execution path without package-specific scheduler or Cache logic.

## Executor evidence

This records executor completion only. Ticket 17 must not start until the
Controller independently runs the cumulative Tickets 01–16 gate and accepts
this state. Any joint-test regression must be returned to the Ticket 16
executor for repair before that next Ticket starts.

- Fixed implementation/review base:
  `f5e5f21e4ca22f634573389782af89e1bbccac71`.
- Implementation and review-fix commits: `a183f84`, `7413408`, `9e94f1f`,
  and `a1b1115`.
- Joint Tickets 01–16 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation/derivation,
  Result replay, intrinsic scoring, pairwise scoring, the Contract Test Kit,
  protein I/O, deterministic prompt authoring, stochastic registration,
  randomness identity/Cache, masking, insertion, and the public journey:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_contract_test_kit_v2.py tests/test_protein_io_v2.py
  tests/test_protein_io_artifacts_v2.py tests/test_prompt_authoring_v2.py
  tests/test_prompt_authoring_behavior_v2.py
  tests/test_prompt_authoring_prompt_v2.py
  tests/test_prompt_stochastic_registration_v2.py
  tests/test_prompt_stochastic_cache_v2.py
  tests/test_prompt_random_mask_v2.py
  tests/test_prompt_random_insert_masked_v2.py
  tests/test_prompt_stochastic_public_v2.py` → `387 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1069 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T132018.230344Z-81629-3cd90f1a628a6cbb`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T132247.796201Z-82468-3cc7a656c32d6315`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T132337.160388Z-82663-5fb40228b2a4788f`.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and the
  zero-operation-specific-`prompt_authoring.random`-literal Core scan passed
  at clean implementation HEAD `a1b1115`.
- Parallel `/code-review` Standards and Spec reviewers drove repairs for
  bounded randomness declarations, linear-time boundary sampling, null-seed
  Cache exclusion, canonical effective eligibility sets, one frozen
  randomness snapshot shared by Cache safety, Result Identity, and execution,
  and focused test-file sizes. Both final review axes returned `APPROVE` at
  `a1b1115`.
