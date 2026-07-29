# 13 — Consolidate protein I/O

**What to build:** A Workflow can import sequence or structure data from Project-scoped inputs and export sequence or structure results as validated, Run-bound artifacts through one cohesive `protein_io` Module Package, without exposing reusable filesystem paths.

**Blocked by:** 12 — Prove the zero-Core extension journey.

**Status:** completed

- [x] Sequence import, structure import, sequence export, and structure export each have one v2 Node Definition and are registered by the single `protein_io` Module Package.
- [x] Import consumes a trusted Project-scoped value or artifact reference rather than an arbitrary private host path embedded in a Workflow.
- [x] Parsed sequence and structure values are validated, canonically encoded, content-digested, and published through exact nominal Port Types.
- [x] Export produces opaque standalone or Candidate artifact references in Run Projection, not absolute or Run-relative path outputs.
- [x] Artifact retrieval revalidates Project/Run ownership, output Port, artifact kind, media type, size, and digest and resists traversal, symlink, no-follow, and cross-scope reads.
- [x] Multiple structures and Candidates retain their identities and deterministic output slots; structure exports preserve the required provider/native serialization semantics.
- [x] Cache replay rematerializes current-Run artifacts without reusing another Run's temporary path or claiming a new scientific Invocation.
- [x] Round-trip fixtures cover valid sequence and structure formats, malformed input, artifact tampering, cross-Run reuse attempts, and the fifteen distinct PDB export shape required by canonical acceptance.
- [x] The package passes the shared Contract Test Kit and requires no `protein_io` special case in Core.

## Executor evidence

This records executor completion only. Ticket 14 must not start until the
Controller independently runs the cumulative Tickets 01–13 gate and accepts
this state.

- Fixed implementation/review base:
  `81fcd5dcbeb93e84ff9f735d3ebdda934e5bbfc4`.
- Implementation and review-fix commits: `60be5b5`, `8b9ef30`, `aeb196c`,
  `791f1c8`, `72ae53d`, and `96a29d0`.
- Joint Tickets 01–13 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation/derivation,
  Result replay, intrinsic scoring, pairwise scoring, the Contract Test Kit,
  and protein I/O:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_contract_test_kit_v2.py tests/test_protein_io_v2.py
  tests/test_protein_io_artifacts_v2.py` → `321 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1007 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T103505.398659Z-53872-44667229b0e0c0f8`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T103705.069546Z-54483-17afa58e256dc798`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T103754.488724Z-54603-b0be061ce3f73b4b`.
- `compileall`, `uv lock --check`, `uv pip check`, `git diff --check`, and the
  zero-`protein_io`-literal Core scan passed at clean implementation HEAD
  `96a29d0d8bc8799967d476953256d314f8d29d70`.
- Parallel `/code-review` Standards and Spec reviewers drove repairs for
  generic nominal artifact publication, Project-resource Result Identity,
  opaque upload references, durable post-restart artifact binding/media
  validation independent of the current Catalog, compile-time structure-input
  XOR, closed media grammar, and bounded test-file size. All findings received
  regressions; both final review axes returned `APPROVE` at `72ae53d`.

## Controller cumulative acceptance

Before Ticket 14 started, Controller independently accepted executor commit
`bb5427e491a0e50da85a470ffda37e393249c52b` against the previously accepted
Tickets 01–12 gate `81fcd5dcbeb93e84ff9f735d3ebdda934e5bbfc4`.

- Joint Tickets 01–13 focused suites:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_contract_test_kit_v2.py tests/test_protein_io_v2.py
  tests/test_protein_io_artifacts_v2.py` → `321 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1007 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T104124.306735Z-55014-61c4fa625853a389`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T104323.996468Z-55609-67acd63b1dd3a026`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T104411.987220Z-55748-70b9be458ad68b06`.
- `git diff --check
  81fcd5dcbeb93e84ff9f735d3ebdda934e5bbfc4...bb5427e491a0e50da85a470ffda37e393249c52b`
  passed.

No Controller regression was found, so Ticket 13 is accepted and Ticket 14
may start.
