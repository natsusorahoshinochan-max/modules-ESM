---
status: accepted
---

# Weighted Rank combines explicit dimensionless utilities

Weighted Rank must not add canonical raw values from different Metrics. Every
selected Metric and Method requires an explicit, versioned, auditable Utility
Transform to a dimensionless value in `[0, 1]`; weights apply only after that
transformation, and a missing or incompatible transform makes the Workflow
invalid.

The Workflow Selection Objective owns the exact Metric, Method, and Observation
Context selector, Utility Transform ID, version and parameters, weight, and
missing-value policy. Metric Definitions describe scientific measurements and
do not own task preferences or implicit default Utilities. Transform
implementations are controlled, versioned production registrations; Workflows
cannot supply arbitrary Python. Every Utility Transform has an exact ID,
version, and contract digest in the FrozenCatalog. Missing, duplicate, or
conflicting Transform registrations fail startup or Workflow compilation
rather than selecting an implementation implicitly.

For example, canonical pLDDT `80` can use the declared linear transform
`x / 100`, while pTM `0.8` can use identity, giving both a utility of `0.8`
before weighting. Dataset-relative implicit min-max normalization and
range-based transform guessing are forbidden. The effective transform identity,
version, parameters, and missing policy must be persisted and recorded in run
provenance. Weights must be finite and non-negative, with at least one positive
weight; execution normalizes them by their sum and records both declared and
effective weights. Negative weights and implicit direction reversal are
forbidden, and a missing observation is an error unless the objective
explicitly declares another supported policy.
