---
status: accepted
---

# Scores identify a Candidate, Metric, Method, Observation Context, and value

A Score Observation is not a value attached only to a `score_id`. Its stable
identity is the Candidate being evaluated, the Metric being observed, the exact
Method or model variant used, and a typed Observation Context. The value is
interpreted through, but is not itself part of, that identity:

```text
Candidate + Metric + Method + Observation Context -> Value
```

An intrinsic observation uses the fixed intrinsic Observation Context. A pairwise or
reference-based observation records explicit subject roles, the reference
Candidate identity and content digest, and any result-defining normalization.
Observation Context is canonical and content-addressable rather than free-form `details` or
a suffix embedded in `score_id`.

Module Packages declare Metric Definitions in their public YAML and the Metric
view of the FrozenCatalog merges them at startup. Metric Definitions also
declare the allowed Observation Context schema. Multiple packages may declare the same
Metric only when scientific meaning, value shape, unit, direction, canonical
range, granularity, aggregation, and Observation Context semantics agree; a conflict fails
startup. Persisted Workflows and selectors target an exact Metric, Method, and
Observation Context selector rather than allowing the runtime to choose an arbitrary
implementation or reference.

This separation is required because one Method can emit several Metrics, as in
Protein-Sol, and one Metric can be observed by several model variants, as in
SoluProt. Provider or deployment identity remains provenance unless it changes
the scientific Method, so it does not enter Score Observation's scientific
identity. Any result-affecting Binding, Adapter, implementation, or deployment
identity still enters Result Identity under ADR-0031. Identical observations
may be deduplicated, but the same
identity with conflicting values, or an undeclared multiplicity, fails closed
unless an explicit aggregation contract applies. ADR-0031 defines stable
Candidate and Result Identity across Cache replay.
