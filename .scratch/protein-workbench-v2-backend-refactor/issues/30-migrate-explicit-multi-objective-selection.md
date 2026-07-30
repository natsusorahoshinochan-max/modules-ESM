# 30 — Migrate explicit multi-objective selection

**What to build:** A Workflow can perform weighted ranking, Pareto selection, and diversity selection from exact scientific objectives whose utilities, scopes, weights, missing policies, and diversity method are explicit and reproducible.

**Blocked by:** 27 — Produce scoped TM-score Observations; 29 — Migrate deterministic Candidate selection.

**Status:** awaiting-controller

- [x] Weighted rank, Pareto selection, and diversity selection each have one v2 Node Definition in the existing `selection` package.
- [x] Every objective fixes Candidate and Score Collection inputs, source partition, Metric, Method, Context profile, match cardinality, Utility Transform, parameters, weight, and missing policy.
- [x] Utility Transforms are versioned Catalog contracts with explicit compatible input and `[0,1]` output behavior; Workflow data cannot supply arbitrary Python.
- [x] Weights are finite and non-negative with at least one positive value, are normalized at execution, and retain declared and effective values in Result Identity and provenance.
- [x] Negative weights, implicit direction reversal, raw Metric addition, hidden dataset-relative min-max, range guessing, and undeclared imputation are rejected.
- [x] Pareto dominance and diversity distance operate on declared dimensionless utilities or an exact diversity Method rather than ambiguous free-form score names.
- [x] Tie behavior and final ordering are deterministic and stable across Runs and Cache replay while preserving original Candidate identity and lineage.
- [x] Canonical fixtures prove that fixed-3GB1 and paired-ESM3 TM-score objectives remain isolated and yield the accepted weighted top three.
- [x] All three Nodes pass compiler capability checks, CTK, public execution, installed discovery, and conflict/missing-value regressions.

## Executor evidence

- Accepted base: `4adf57234e4da0f4e422c48a43c671789a4dc176`.
- Primary implementation commit: `8930446` (`feat: migrate explicit multi-objective selection`).
- Review-fix commits: `929b764`, `8a52b4e`, `f7352c5`, and `4e50ba6`.
- Ticket-focused tests: `tests/test_multi_objective_selection_v2.py` — 13 passed.
- Focused cross-slice tests: Run execution, multi-objective selection, selection, scoring, Module Packages, compiler, scoped TM-score Observations, Port Types, and public protocol — 273 passed.
- Cumulative v2 tests: 588 passed.
- Routine verification: 1277 passed, 52 deselected; retained at `verification-results/routine/20260730T065735.368951Z-12200-0848a56f2af13005`.
- Deterministic acceptance: 10 passed, 5 deselected; retained at `verification-results/deterministic-acceptance/20260730T070257.891443Z-20671-dce9ef1c5b5ff850`.
- Installed-package verification: 3 passed; retained at `verification-results/installed-package/20260730T070411.430403Z-21402-0f0ab553c322f162`.
- Static/package checks: `git diff --check`, compileall, `uv lock --check`, and `uv pip check` passed.
- Parallel `/code-review` at exact code HEAD `4e50ba644b72eeb7d42f6952521668072bd1f300`: Standards PASS and Spec PASS with 0 Critical/High/Medium findings after closing actual-method projection, multi-consumer projection, and exact Ledger causality.
- Handoff boundary: executor work is complete and awaits the Controller-owned joint Ticket 01–30 gate; this ticket must not be marked `completed` until that cumulative gate passes.
