---
status: accepted
---

# Weighted Rank combines explicit dimensionless utilities

Weighted Rank must not add canonical raw values from different Metrics. Every
selected Metric and Method requires an explicit, versioned, auditable Utility
Transform to a dimensionless value in `[0, 1]`; weights apply only after that
transformation, and a missing or incompatible transform makes the Workflow
invalid.

For example, canonical pLDDT `80` can use the declared linear transform
`x / 100`, while pTM `0.8` can use identity, giving both a utility of `0.8`
before weighting. Dataset-relative implicit min-max normalization and
range-based transform guessing are forbidden. The effective transform identity,
version, and parameters must be persisted and recorded in run provenance;
whether the Metric Definition or Workflow objective owns that configuration is
a separate decision.
