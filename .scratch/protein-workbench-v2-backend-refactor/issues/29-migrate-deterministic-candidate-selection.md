# 29 — Migrate deterministic Candidate selection

**What to build:** A Workflow can filter, sort, and take the top Candidates from an explicitly scoped set of Observations with deterministic missing-value and tie behavior while preserving the selected Candidates' original identities.

**Blocked by:** 28 — Preserve partitions in collection operations.

**Status:** completed

- [x] Filter, sort, and top-k each have one v2 Node Definition in a single `selection` Module Package.
- [x] Selection consumes an explicit Candidate input and exact Score Collection source partition rather than discovering scores globally.
- [x] Filter conditions and sort keys resolve exact Metric, Method, Context profile, and match cardinality through controlled declarative contracts, not arbitrary Python or free-form score names.
- [x] Missing, duplicate, conflicting, or out-of-scope Observations follow the declared policy and default to fail closed.
- [x] Sort order follows Metric direction or an explicit Utility contract without implicit sign reversal, range guessing, or raw cross-Metric comparison.
- [x] Ties have a declared deterministic resolution independent of Run UUID, process hash order, Cache state, or incidental collection order.
- [x] Top-k validates bounds and preserves original Candidate identities, lineage, content, and relative ranking evidence rather than producing replacement Candidates.
- [x] Compiler rejects unsatisfiable selectors before provider execution, and runtime revalidates dynamic subject cardinality before output publication.
- [x] The package slice passes CTK, Cache replay, public protocol, and deterministic failure tests.

## Executor evidence

- Accepted base: `7d5f7fd8f31f1edaafbc1807b0288dbc8e414cb9`.
- Implementation commits: `2394d7a` (`feat: migrate deterministic candidate selection`) and `b08d7df` (`fix: bind selection cache to resolved objective`).
- Ticket-focused tests: `tests/test_selection_v2.py` — 11 passed.
- Focused cross-slice tests: selection, scoring, pairwise scoring, TM-score observations, collection operations, Module Packages, CTK, compiler, execution, Cache, and public protocol — 299 passed.
- Cumulative v2 tests: 575 passed.
- Routine verification: 1264 passed, 52 deselected; retained at `verification-results/routine/20260730T055435.442708Z-75466-b37f4a44539d9e77`.
- Deterministic acceptance: 10 passed, 5 deselected; retained at `verification-results/deterministic-acceptance/20260730T055953.458189Z-82872-6cfe06dc1bf33c15`.
- Installed-package verification: 3 passed; retained at `verification-results/installed-package/20260730T060108.314676Z-83553-b8b7a1d143bcaca2`.
- Static/package checks: `git diff --check`, compileall, `uv lock --check`, and `uv pip check` passed.
- Parallel `/code-review`: Standards APPROVE and Spec APPROVE after repairing shared selection resolution, out-of-scope duplicate handling, and Result Identity/Cache binding to the resolved objective.
- Handoff boundary: executor work is complete and awaits the Controller-owned joint Ticket 01–29 gate; this ticket must not be marked `completed` until that cumulative gate passes.

## Controller joint-test evidence

- Previous accepted multi-ticket gate:
  `7d5f7fd8f31f1edaafbc1807b0288dbc8e414cb9`; independently tested Ticket 29
  executor SHA: `74dd525f2f7461c081f920849e5e3a694fcb7430`.
- Tickets 01–29 cumulative v2 gate:
  `uv run --no-sync pytest -q tests/*_v2.py` →
  `575 passed`.
- Ticket 29 cross-package focused gate:
  `uv run --no-sync pytest -q tests/test_selection_v2.py
  tests/test_scoring_v2.py tests/test_pairwise_scoring_v2.py
  tests/test_tm_score_observations_v2.py tests/test_collection_ops_v2.py
  tests/test_module_packages_v2.py tests/test_contract_test_kit_v2.py
  tests/test_workflow_compiler_v2.py tests/test_run_execution_v2.py
  tests/test_result_cache_v2.py tests/test_public_protocol_v2.py` →
  `299 passed`.
- Full routine joint gate:
  `uv run --no-sync python scripts/verify_backend.py routine` →
  `1264 passed, 52 deselected`; retained result
  `verification-results/routine/20260730T060635.273467Z-87897-f7276ce8505556dd`.
- Deterministic acceptance:
  `uv run --no-sync python scripts/verify_backend.py
  deterministic-acceptance` →
  `10 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260730T061144.124251Z-95567-53d58413b6677b70`.
- Installed-package isolation:
  `uv run --no-sync python scripts/verify_backend.py installed-package` →
  `3 passed`; retained result
  `verification-results/installed-package/20260730T061302.414896Z-96193-ed31837f8c2e1263`.
- All three retained Controller records report
  `project_revision=74dd525f2f7461c081f920849e5e3a694fcb7430` and
  `project_dirty=false`. The worktree was clean before this evidence-only
  status update, and no cross-ticket regression was found.
