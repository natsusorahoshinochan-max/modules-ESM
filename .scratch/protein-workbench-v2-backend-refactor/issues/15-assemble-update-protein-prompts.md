# 15 — Assemble and update ProteinPrompts

**What to build:** A Workflow can combine aligned residue tracks and function annotations into a validated ProteinPrompt and update its sequence through generic prompt-authoring Nodes, without depending on an ESM-3-specific helper or undeclared payload fields.

**Blocked by:** 14 — Consolidate residue layout and track editing.

**Status:** completed

- [x] Prompt assembly, function annotation, and generic prompt sequence update each have one v2 Node Definition in the existing `prompt_authoring` package.
- [x] Prompt assembly accepts only declared layout, sequence, structure, visibility, secondary-structure, SASA, and function-annotation inputs with exact Port contracts.
- [x] All present tracks have the same effective residue layout and legal symbol/value domains; incomplete optional tracks remain explicit rather than being synthesized from UI-only fields.
- [x] Function annotations validate label, interval, chain/layout correspondence, ordering, and overlap semantics and retain canonical provenance.
- [x] Sequence update preserves every unaffected track and residue identity while rejecting incompatible length or illegal residue changes.
- [x] The former ESM-3-specific prompt sequence helper is absorbed as a generic scientific operation rather than retained as duplicate package glue.
- [x] Node and Binding parameters contain only accepted scientific choices; credentials, device, model, endpoint, and runtime paths are absent.
- [x] Canonical fixtures prove that ProteinPrompt scientific intent survives codec round-trip and the later ESM-3 adapter boundary.
- [x] All three Nodes pass the common Contract Test Kit and are discoverable from source and installed artifacts through one package registration.

## Executor evidence

This records executor completion only. Ticket 16 must not start until the
Controller independently runs the cumulative Tickets 01–15 gate and accepts
this state.

- Fixed implementation/review base:
  `5273f2d5b0d984e32542c10e1c4404048997e3db`.
- Implementation and review-fix commits: `f71924f` and `4c7f2d3`.
- Joint Tickets 01–15 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation/derivation,
  Result replay, intrinsic scoring, pairwise scoring, the Contract Test Kit,
  protein I/O, residue-track authoring, and ProteinPrompt authoring:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_contract_test_kit_v2.py tests/test_protein_io_v2.py
  tests/test_protein_io_artifacts_v2.py tests/test_prompt_authoring_v2.py
  tests/test_prompt_authoring_behavior_v2.py
  tests/test_prompt_authoring_prompt_v2.py` → `362 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1044 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T122101.033061Z-71358-8bcd301315cc5d49`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T122310.436653Z-72037-1d2028dcace1cdea`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T122359.566385Z-72251-41d65ce5a24a32ab`.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and the
  zero-operation-specific-`prompt_authoring`-literal Core scan passed at clean
  implementation HEAD `4c7f2d3d335a8b432d649ad6e81b8ff9f2878704`.
- Parallel `/code-review` Standards and Spec reviewers drove repairs for
  immutable legacy `2.0.0` Port contracts, explicit canonical `2.1.0`
  annotation/Prompt contracts, nested contract identity, focused production
  modules, one typed annotation validator, and complete removal of the legacy
  ESM-3-specific sequence helper. Both final review axes returned `APPROVE` at
  `4c7f2d3`.

## Controller cumulative acceptance

Before Ticket 16 started, Controller independently accepted executor commit
`338dda476a87739a6ec1e14353adfd96a2eb2aab` against the previously accepted
Tickets 01–14 gate `5273f2d5b0d984e32542c10e1c4404048997e3db`.

- Joint Tickets 01–15 focused suites:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_contract_test_kit_v2.py tests/test_protein_io_v2.py
  tests/test_protein_io_artifacts_v2.py tests/test_prompt_authoring_v2.py
  tests/test_prompt_authoring_behavior_v2.py
  tests/test_prompt_authoring_prompt_v2.py` → `362 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1044 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T122643.813268Z-72691-00fb90f3532653a9`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T122854.272334Z-73309-a11ac848d05796a4`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T122942.895394Z-73433-e87859a773ffb24c`.
- `git diff --check
  5273f2d5b0d984e32542c10e1c4404048997e3db...338dda476a87739a6ec1e14353adfd96a2eb2aab`
  passed.

No Controller regression was found, so Ticket 15 is accepted and Ticket 16
may start.
