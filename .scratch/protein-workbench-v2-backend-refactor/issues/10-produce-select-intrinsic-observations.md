# 10 — Produce and select intrinsic Observations

**What to build:** A Workflow can run a fixed scoring Binding, receive scientifically typed intrinsic Observations, and select Candidates through an explicit versioned Utility objective without relying on an ambiguous `score_id` or adding raw Metrics.

**Blocked by:** 09 — Replay project-scoped typed results.

**Status:** awaiting-controller

- [x] Metric Definition declares exact identity, value shape, unit, direction, canonical range, granularity, aggregation, validity/masking, and allowed Observation Context schema.
- [x] Method fixes the exact scientific algorithm or model identity, while each Binding declares the output Port, Metric, intrinsic Context profile, subject grain, source role, and guaranteed multiplicity it produces.
- [x] Observation identity is Candidate, Metric, Method, and typed Context; Value is validated but does not become part of that identity.
- [x] A single Method can produce multiple declared Metrics, and the same Metric can be produced by multiple exact Methods without collision or implicit selection.
- [x] Compilation rejects an objective when the selected Binding cannot guarantee the requested observation before any provider call.
- [x] Selection Objective fixes its Candidate and Score Collection inputs, Metric, Method, Context selector, Utility Transform ID/version/parameters, weight, match cardinality, and missing-value policy.
- [x] Utility output is constrained to `[0,1]`; weights are finite and non-negative with at least one positive value, are normalized at execution, and retain both declared and effective values in provenance.
- [x] Negative weights, implicit direction reversal, dataset-relative min-max, range guessing, raw cross-Metric addition, and arbitrary Workflow Python are rejected.
- [x] Identical observation identity/value may deduplicate, while conflicting values or undeclared multiplicity fail closed; missing observations default to error.

## Executor evidence

- Fixed base: `82db2cb37ebfdefb67b549002f08a2bfa05b5b9b`.
- Commits: `44ecdad`, `fe8ad2e`, `900ae80`, `06fd4d1`.
- Tickets 01–10 focused joint suite: `269 passed`.
- Routine gate: `955 passed, 44 deselected`; retained at `verification-results/routine/20260729T070400.972779Z-13884-8dc8929dc77cf17c`.
- Deterministic acceptance: `9 passed, 5 deselected`; retained at `verification-results/deterministic-acceptance/20260729T070551.481740Z-14715-b64130199d4ca12b`.
- Installed-package gate: `3 passed`; retained at `verification-results/installed-package/20260729T070645.687513Z-15248-a5f0f1191e977b23`.
- `compileall`, `uv lock --check`, `uv pip check`, and `git diff --check` passed.
- Final Standards and Spec reviews: `APPROVE`.
- Ticket 11 observation propagation and Ticket 29 general top-k selection remain outside this ticket.
