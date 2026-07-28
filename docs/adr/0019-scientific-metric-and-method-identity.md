---
status: accepted
---

# Scores identify a Metric, Method, Candidate, and value

A score is a scientific observation, not a value attached only to a
`score_id`. Its stable identity is the Candidate being evaluated, the Metric
being observed, and the exact Method or model variant used; the observed value
is interpreted through that identity.

Module Packages declare Metric Definitions in their public YAML and the Metric
Registry merges them at startup. Multiple packages may declare the same Metric
only when scientific meaning, value shape, unit, direction, canonical range,
granularity, and aggregation semantics agree; a conflict fails startup.
Persisted Workflows and selectors target an exact Metric plus Method rather
than allowing the runtime to choose an arbitrary implementation.

This separation is required because one Method can emit several Metrics, as in
Protein-Sol, and one Metric can be observed by several model variants, as in
SoluProt. Provider or deployment identity remains provenance unless it changes
the scientific Method.
