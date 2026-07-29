# 11 — Resolve pairwise Observation counterparts

**What to build:** A Workflow can score each subject against its exact dynamic counterpart within an explicitly selected Score Collection partition, and both compilation and execution reject ambiguous pairings or cross-objective contamination.

**Blocked by:** 10 — Produce and select intrinsic Observations.

**Status:** completed

- [x] Pairwise Context uses typed participant roles and records subject identity, exact reference Candidate identity/content digest, pairing mode, and result-defining normalization.
- [x] Produced Observation contracts express fixed sets and controlled pass-through, union, or filter propagation while preserving source partitions and declared multiplicity.
- [x] Compiler derives the exact observation capability of each relevant output Port without executing arbitrary selector or lineage-query code.
- [x] Selection Objective binds an explicit Candidate input, Score Collection source partition, Metric, Method, canonical Context profile, and per-subject match cardinality.
- [x] Runtime resolves the exact generated reference for each subject inside the declared partition; zero matches and multiple matches fail closed by default.
- [x] Pairing never depends on collection order, free-form suffixes, incidental lineage guessing, or a global reference that is absent from the declared Context.
- [x] A fixture with fixed-reference and per-subject counterpart objectives proves that the two partitions cannot cross-match even when Metric names and values overlap.
- [x] Invalid source scope, Context role/profile, normalization, Method, or cardinality fails before provider invocation when statically knowable and otherwise before selection publication.

## Executor evidence

This records executor completion only. Ticket 12 must not start until the
Controller independently runs the cumulative Tickets 01–11 gate and accepts
this state.

- Fixed implementation/review base:
  `257cdf7fa5b8e36753768aeba0b2a11d3792dc65`.
- Implementation and review-fix commits: `10d29c7`, `d40f49c`, and
  `16b254e`.
- Joint Tickets 01–11 focused regression across public protocol, Port Types,
  Module Packages, Workflow compiler, Run execution, cancellation/derivation,
  Result replay, intrinsic scoring, and pairwise scoring:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py` →
  `287 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `973 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T081017.917212Z-27654-318d7ce5dcd79e6f`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T081216.706295Z-28270-7f7766a86e5e66ff`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T081216.706294Z-28269-e1815da49d2b0f7f`.
- `python -m json.tool`, `compileall`, `uv lock --check`, `uv pip check`, and
  `git diff --check` passed at clean implementation HEAD
  `16b254ea46dadc89f808a5c4deb3922cef970474`.
- Parallel `/code-review` Standards and Spec reviewers drove fixes for a
  self-asserted counterpart relation, an open propagation filter, propagation
  multiplicity mismatch, incomplete output-origin identity normalization,
  partition-contaminated Observation identity, and conflicting Candidate
  digests. All findings were repaired with regressions; both final review axes
  returned `APPROVE` at `16b254e`.

## Controller cumulative acceptance

Before Ticket 12 started, Controller independently accepted executor commit
`39670d25ca92026556345e0d3beffbe27f289356` against the previously accepted
Tickets 01–10 gate `257cdf7fa5b8e36753768aeba0b2a11d3792dc65`.

- Joint Tickets 01–11 focused suites:
  `uv run --no-sync python -m pytest -q tests/test_public_protocol_v2.py
  tests/test_port_types_v2.py tests/test_module_packages_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_run_cancel_derive_v2.py tests/test_result_cache_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py` →
  `287 passed`.
- Cumulative routine gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `973 passed, 44 deselected`; retained result
  `verification-results/routine/20260729T081456.978939Z-28910-782cddcdca52c25c`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` → `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260729T081651.030148Z-29794-af7c8a959bf048a3`.
- Installed artifact:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260729T081737.039385Z-30000-5e5ee58ecc909426`.
- `git diff --check
  257cdf7fa5b8e36753768aeba0b2a11d3792dc65...39670d25ca92026556345e0d3beffbe27f289356`
  passed.

No Controller regression was found, so Ticket 11 is accepted and Ticket 12
may start.
