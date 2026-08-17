# 09 — Replay project-scoped typed results

> Historical completion evidence only. Checksums, symlink/security probes, Readiness-before-Cache, restart reconstruction, and old verification tiers mentioned below are not current requirements.

**What to build:** Repeating the same scientifically identified computation within one Project can safely replay complete typed results and stable Candidates, while changed scientific identity, another Project, or ambiguous provenance can never reuse them.

**Blocked by:** 06 — Close dispositions across branch failures.

**Status:** completed

- [x] Result Identity uses the `protein-workbench-cache/v2` namespace and includes every result-affecting Node, Port, Binding, Method, implementation, model, source, input, parameter, randomness, Metric, Context, and Utility contract.
- [x] Project ID, Run ID, Node Instance ID, timestamps, credentials, private paths, presentation metadata, and performance-only choices do not enter Result Identity.
- [x] Candidate identity is run-independent and derives from producer Result Identity, output/sample slot, parent Candidate identities, and content digest rather than from Run UUID or content alone.
- [x] Cache lookup remains after all selected-Binding Readiness checks, and a hit produces succeeded/cache-replayed disposition without an Operation Attempt or Engine Invocation.
- [x] Physical storage remains Project-scoped and contains only complete, successful, validated, cache-eligible values encoded by the registered Port Type codec, never filesystem paths.
- [x] Failed, cancelled, interrupted, outcome-unknown, partial, uncontrolled-stochastic, insufficiently identified, or required-standalone-artifact results are not cached.
- [x] Missing result-affecting identity disables cross-Run caching; the same Result Identity with conflicting output or contract metadata returns `cache_identity_conflict` without overwrite or first-write-wins behavior.
- [x] Replay preserves Candidate identity and lineage and records current-Run materialization plus producer provenance without copying historical Availability, Readiness, Operation, or Invocation facts.
- [x] Tests cover deterministic hits, identity-changing misses, Project isolation, typed-codec corruption, path rejection, and conflict handling through public projections.

## Executor evidence

This records executor completion only. Ticket 10 must not start until the
Controller independently runs the cumulative Tickets 01–09 gate and accepts
this state.

- Fixed implementation/review base:
  `80949598dcb0a36117ecc14bd20fb7e2abaebd7b`.
- Implementation and review-fix commits: `a54b688`, `cf50219`, `4d3b760`,
  `1b47549`, and `50923ed`.
- Focused Result Identity, Cache, Run, cancellation/derivation, and public
  protocol acceptance:
  `uv run --no-sync python -m pytest -q tests/test_result_cache_v2.py
  tests/test_run_execution_v2.py tests/test_run_cancel_derive_v2.py
  tests/test_public_protocol_v2.py` → `94 passed`.
- Joint Tickets 01–09 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation/derivation,
  and Result replay → `242 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `928 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T053658.636832Z-907-10d85a307c197f85`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T053900.249304Z-1595-1554d016f32b8400`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T053900.249170Z-1596-85bbfbf7ff023bfa`.
- `compileall`, `pip check`, `uv lock --check`, and
  `git diff --check 80949598...HEAD` passed. No standalone mypy/pyright
  configuration is installed, so no separate static-type result is claimed.
- Parallel `/code-review` Standards and Spec reviewers found and drove fixes
  for incomplete Utility/randomness/replay provenance identity, Candidate
  identity ambiguity, non-atomic Cache publication, unresolved Port/input
  identity, over-broad presentation stripping, Candidate codec bypass, and
  manifest-based producer gating. All findings were repaired with public
  regressions; both final review axes returned `APPROVE` at `50923ed`.

## Controller cumulative acceptance

Before Ticket 10 started, Controller independently accepted executor commit
`54f56677e76e709ac1c33c082f56781a32506286` against the previously accepted
Tickets 01–08 gate `80949598dcb0a36117ecc14bd20fb7e2abaebd7b`.

- Joint Tickets 01–09 focused suites:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py` →
  `242 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `928 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T054158.542419Z-2126-75ab9b24125a4b6d`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T054347.981848Z-2709-bdca6b0cd8e11c46`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T054431.355048Z-2832-a934da32967f1534`.
- `git diff --check
  80949598dcb0a36117ecc14bd20fb7e2abaebd7b...54f56677e76e709ac1c33c082f56781a32506286`
  passed.

No Controller regression was found, so Ticket 09 is accepted and Ticket 10
may start.
