# 10 — Produce and select intrinsic Observations

**What to build:** A Workflow can run a fixed scoring Binding, receive scientifically typed intrinsic Observations, and select Candidates through an explicit versioned Utility objective without relying on an ambiguous `score_id` or adding raw Metrics.

**Blocked by:** 09 — Replay project-scoped typed results.

**Status:** ready-for-agent

- [ ] Metric Definition declares exact identity, value shape, unit, direction, canonical range, granularity, aggregation, validity/masking, and allowed Observation Context schema.
- [ ] Method fixes the exact scientific algorithm or model identity, while each Binding declares the output Port, Metric, intrinsic Context profile, subject grain, source role, and guaranteed multiplicity it produces.
- [ ] Observation identity is Candidate, Metric, Method, and typed Context; Value is validated but does not become part of that identity.
- [ ] A single Method can produce multiple declared Metrics, and the same Metric can be produced by multiple exact Methods without collision or implicit selection.
- [ ] Compilation rejects an objective when the selected Binding cannot guarantee the requested observation before any provider call.
- [ ] Selection Objective fixes its Candidate and Score Collection inputs, Metric, Method, Context selector, Utility Transform ID/version/parameters, weight, match cardinality, and missing-value policy.
- [ ] Utility output is constrained to `[0,1]`; weights are finite and non-negative with at least one positive value, are normalized at execution, and retain both declared and effective values in provenance.
- [ ] Negative weights, implicit direction reversal, dataset-relative min-max, range guessing, raw cross-Metric addition, and arbitrary Workflow Python are rejected.
- [ ] Identical observation identity/value may deduplicate, while conflicting values or undeclared multiplicity fail closed; missing observations default to error.
