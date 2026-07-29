# 17 — Consolidate structure transforms

**What to build:** A Workflow can select chains, extract a backbone, or derive a sequence from a structure through explicit, provenance-bearing scientific conversion Nodes in one `structure_transform` Module Package.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** completed

- [x] Chain selection, backbone extraction, and sequence extraction each have one independent v2 Node Definition and share one cohesive package registration.
- [x] Exact nominal input/output Port Types make every conversion visible in the Workflow and prevent implicit structure-to-sequence or full-atom-to-backbone coercion.
- [x] Chain selection validates requested chain identities, deterministic ordering, empty results, duplicated requests, and multi-model behavior.
- [x] Backbone extraction defines and validates retained atoms, residues, chain breaks, alternate locations, missing atoms, and content identity.
- [x] Sequence extraction defines treatment of non-protein residues, unknown residues, chain separation, and residue-to-sequence correspondence.
- [x] Every output is canonical, content-digested, and carries producer/output lineage suitable for Result Identity and Candidate derivation.
- [x] Import-transform-export public journeys prove that artifacts stay Run-bound and that no private path crosses a Port or enters scientific identity.
- [x] The package removes duplicated conversion registration/Definition glue and passes the common CTK without Core type or dispatch edits.

## Executor evidence

This records executor completion only. Ticket 18 must not start until the
Controller independently runs the cumulative Tickets 01–17 gate and accepts
this state. Any joint-test regression must be returned to this Ticket 17
executor for repair before that next Ticket starts.

- Fixed implementation/review base:
  `62c3688862d4b60a9941f204ac31c0e77f8c16ab`.
- Implementation and review-fix commits: `7cbc70e`, `43b6251`, `7b5480e`,
  and `0388a50`.
- Joint Tickets 01–17 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation/derivation,
  Result replay, intrinsic scoring, pairwise scoring, the Contract Test Kit,
  protein I/O, deterministic and stochastic prompt authoring, structure
  transform contracts/behavior, and the public import-transform-export
  journey:
  `uv run --no-sync python -m pytest --disable-warnings -q
  tests/test_public_protocol_v2.py tests/test_port_types_v2.py
  tests/test_module_packages_v2.py tests/test_workflow_compiler_v2.py
  tests/test_run_execution_v2.py tests/test_run_cancel_derive_v2.py
  tests/test_result_cache_v2.py tests/test_scoring_v2.py
  tests/test_pairwise_scoring_v2.py tests/test_contract_test_kit_v2.py
  tests/test_protein_io_v2.py tests/test_protein_io_artifacts_v2.py
  tests/test_prompt_authoring_v2.py
  tests/test_prompt_authoring_behavior_v2.py
  tests/test_prompt_authoring_prompt_v2.py
  tests/test_prompt_stochastic_registration_v2.py
  tests/test_prompt_stochastic_cache_v2.py
  tests/test_prompt_random_mask_v2.py
  tests/test_prompt_random_insert_masked_v2.py
  tests/test_prompt_stochastic_public_v2.py
  tests/test_structure_transform_v2.py
  tests/test_structure_transform_behavior_v2.py
  tests/test_structure_transform_public_v2.py` → `405 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1088 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T135621.389105Z-87904-51e5447bc2bc27f0`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T135842.230207Z-88598-61237791707e23f2`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T135930.739794Z-88726-a0d9ecbbc9c9b010`.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and the
  zero-Core-diff check passed at clean implementation HEAD `0388a50`.
- Parallel `/code-review` Standards and Spec reviewers drove repairs for
  canonical TER/chain segmentation, residue-name consistency, explicit
  backbone nominal export bridging, deterministic chain serial numbering,
  and alternate-location preservation. Both final review axes returned
  `APPROVE` at `0388a50`.

## Controller cumulative acceptance

Before Ticket 18 started, Controller independently accepted executor commit
`1a9a9408aea982f00a1e0dec743f60181bb04507` against the previously accepted
Tickets 01–16 gate `62c3688862d4b60a9941f204ac31c0e77f8c16ab`.

- Joint Tickets 01–17 focused suites:
  `uv run --no-sync python -m pytest --disable-warnings -q
  tests/test_public_protocol_v2.py tests/test_port_types_v2.py
  tests/test_module_packages_v2.py tests/test_workflow_compiler_v2.py
  tests/test_run_execution_v2.py tests/test_run_cancel_derive_v2.py
  tests/test_result_cache_v2.py tests/test_scoring_v2.py
  tests/test_pairwise_scoring_v2.py tests/test_contract_test_kit_v2.py
  tests/test_protein_io_v2.py tests/test_protein_io_artifacts_v2.py
  tests/test_prompt_authoring_v2.py
  tests/test_prompt_authoring_behavior_v2.py
  tests/test_prompt_authoring_prompt_v2.py
  tests/test_prompt_stochastic_registration_v2.py
  tests/test_prompt_stochastic_cache_v2.py
  tests/test_prompt_random_mask_v2.py
  tests/test_prompt_random_insert_masked_v2.py
  tests/test_prompt_stochastic_public_v2.py
  tests/test_structure_transform_v2.py
  tests/test_structure_transform_behavior_v2.py
  tests/test_structure_transform_public_v2.py` → `406 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1088 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T140331.236556Z-89121-35fd6e8aa058a44d`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T140552.927269Z-89765-419ef009c57f1772`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T140642.085399Z-89887-1c3a6e064665feaf`.
- `git diff --check
  62c3688862d4b60a9941f204ac31c0e77f8c16ab...1a9a9408aea982f00a1e0dec743f60181bb04507`
  passed.

No Controller regression was found, so Ticket 17 is accepted and Ticket 18
may start.
