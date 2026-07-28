# 30 — Migrate explicit multi-objective selection

**What to build:** A Workflow can perform weighted ranking, Pareto selection, and diversity selection from exact scientific objectives whose utilities, scopes, weights, missing policies, and diversity method are explicit and reproducible.

**Blocked by:** 27 — Produce scoped TM-score Observations; 29 — Migrate deterministic Candidate selection.

**Status:** ready-for-agent

- [ ] Weighted rank, Pareto selection, and diversity selection each have one v2 Node Definition in the existing `selection` package.
- [ ] Every objective fixes Candidate and Score Collection inputs, source partition, Metric, Method, Context profile, match cardinality, Utility Transform, parameters, weight, and missing policy.
- [ ] Utility Transforms are versioned Catalog contracts with explicit compatible input and `[0,1]` output behavior; Workflow data cannot supply arbitrary Python.
- [ ] Weights are finite and non-negative with at least one positive value, are normalized at execution, and retain declared and effective values in Result Identity and provenance.
- [ ] Negative weights, implicit direction reversal, raw Metric addition, hidden dataset-relative min-max, range guessing, and undeclared imputation are rejected.
- [ ] Pareto dominance and diversity distance operate on declared dimensionless utilities or an exact diversity Method rather than ambiguous free-form score names.
- [ ] Tie behavior and final ordering are deterministic and stable across Runs and Cache replay while preserving original Candidate identity and lineage.
- [ ] Canonical fixtures prove that fixed-3GB1 and paired-ESM3 TM-score objectives remain isolated and yield the accepted weighted top three.
- [ ] All three Nodes pass compiler capability checks, CTK, public execution, installed discovery, and conflict/missing-value regressions.
