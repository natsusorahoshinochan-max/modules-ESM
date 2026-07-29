# 14 — Consolidate residue layout and track editing

**What to build:** A Workflow author can build a residue layout, apply explicit residue edits, map tracks between layouts, and override selected residues through one coherent `prompt_authoring` contract whose per-residue values remain aligned and scientifically interpretable.

**Blocked by:** 12 — Prove the zero-Core extension journey.

**Status:** awaiting-controller

- [x] Layout construction, residue editing, track mapping, and track override each have one independent v2 Node Definition under one `prompt_authoring` registration.
- [x] Shared implementation and domain values replace duplicated per-directory Definition loading, registration glue, and ad hoc track parsing.
- [x] Every per-residue track is validated against the target layout, chain boundaries, residue identities, visibility, and nullable-value semantics before publication.
- [x] Residue edits preserve an explicit source-to-target residue map and reject overlaps, out-of-range edits, contradictory chain operations, and length drift.
- [x] Track mapping is an explicit scientific conversion Node with provenance; nominally different tracks are never connected through structural similarity or an implicit coercion.
- [x] Overrides distinguish clearing, preserving, and replacing values and never silently shift downstream residue indices.
- [x] Deterministic inputs produce canonical outputs and stable Result Identities without provider, credential, or environment dependence.
- [x] Differential fixtures cover insertion/deletion boundaries, chain breaks, unmapped residues, optional values, and the accepted secondary-structure layout-shift regression.
- [x] The package slice compiles and executes through the shared CTK and public protocol without Core dispatch changes.

## Executor evidence

This records executor completion only. Ticket 15 must not start until the
Controller independently runs the cumulative Tickets 01–14 gate and accepts
this state.

- Fixed implementation/review base:
  `2442671a3f2b55436a44a5f3ce6677bd7a8d0e86`.
- Implementation and review-fix commits: `9188fd9`, `f38bcec`, `99de243`,
  and `cd0f185`.
- Joint Tickets 01–14 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation/derivation,
  Result replay, intrinsic scoring, pairwise scoring, the Contract Test Kit,
  protein I/O, and prompt authoring:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_contract_test_kit_v2.py tests/test_protein_io_v2.py
  tests/test_protein_io_artifacts_v2.py tests/test_prompt_authoring_v2.py
  tests/test_prompt_authoring_behavior_v2.py` → `339 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1025 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T112119.870703Z-60493-53bd440d8cac62e8`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T112327.057542Z-61380-feaddc0d85a725b5`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T112417.485933Z-61551-f8f87733b3866961`.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and the
  zero-`prompt_authoring`-literal Core scan passed at clean implementation
  HEAD `cd0f18508a8a2258064a42de1b1932f9f0374160`.
- Parallel `/code-review` Standards and Spec reviewers drove repairs for
  explicit Definition resources, operation-specific Method identities,
  closed track kinds, exact layout-carrying nominal Port Types, complete
  residue-map consistency, public structure overrides, accepted
  secondary-structure layout shifts, public-protocol coverage, and exclusive
  named-atom structure coordinates. Every finding received a regression; both
  final review axes returned `APPROVE` at `cd0f185`.
