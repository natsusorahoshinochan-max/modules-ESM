# 29 — Migrate deterministic Candidate selection

**What to build:** A Workflow can filter, sort, and take the top Candidates from an explicitly scoped set of Observations with deterministic missing-value and tie behavior while preserving the selected Candidates' original identities.

**Blocked by:** 28 — Preserve partitions in collection operations.

**Status:** ready-for-agent

- [ ] Filter, sort, and top-k each have one v2 Node Definition in a single `selection` Module Package.
- [ ] Selection consumes an explicit Candidate input and exact Score Collection source partition rather than discovering scores globally.
- [ ] Filter conditions and sort keys resolve exact Metric, Method, Context profile, and match cardinality through controlled declarative contracts, not arbitrary Python or free-form score names.
- [ ] Missing, duplicate, conflicting, or out-of-scope Observations follow the declared policy and default to fail closed.
- [ ] Sort order follows Metric direction or an explicit Utility contract without implicit sign reversal, range guessing, or raw cross-Metric comparison.
- [ ] Ties have a declared deterministic resolution independent of Run UUID, process hash order, Cache state, or incidental collection order.
- [ ] Top-k validates bounds and preserves original Candidate identities, lineage, content, and relative ranking evidence rather than producing replacement Candidates.
- [ ] Compiler rejects unsatisfiable selectors before provider execution, and runtime revalidates dynamic subject cardinality before output publication.
- [ ] The package slice passes CTK, Cache replay, public protocol, and deterministic failure tests.
