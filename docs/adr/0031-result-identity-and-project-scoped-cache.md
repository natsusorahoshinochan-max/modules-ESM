---
status: accepted
---

# Result Identity is canonical while Cache storage remains Project-scoped

Result Identity uses the schema namespace `protein-workbench-cache/v2` and is
derived from the exact resolved Node and Port contracts, Execution Binding,
Method, Adapter, result-affecting implementation, model, checkpoint, source,
and binary identities; canonical typed input identities and content digests;
normalized resolved Node and Binding parameters; effective seed or other
declared randomness; and relevant output, Metric, Observation Context, and
Utility contracts. Project ID, Run ID, Node Instance ID, credentials, private
filesystem paths, timestamps, presentation metadata, and performance-only
environment choices do not participate.

The namespace and identity rules are global, but each physical Cache remains
owned by one Project; identical identities in different Projects do not imply
cross-Project storage or replay. Cache entries contain only complete successful
typed values encoded by their registered Port Type codecs, never absolute or
run-relative paths. A result whose correctness requires a standalone artifact
outside those typed values is non-cacheable.

Failed, cancelled, interrupted, partial, uncontrolled stochastic, and
insufficiently identified remote results are non-cacheable. If any
result-affecting identity cannot be resolved, cross-Run caching for that
Binding is disabled. Cache replay records current-Run materialization and
producer provenance; it does not copy historical Availability, Readiness,
Operation Attempts, or Engine Invocations.

Writing different canonical outputs or contract metadata under an existing
Result Identity is a `cache_identity_conflict` and fails rather than
overwriting, selecting, or silently accepting either entry. Candidate
identities carried by typed values are stable and run-independent. They are
derived from the producer Result Identity, output slot or sample identity,
parent Candidate identities, and content digest, and are preserved across
Cache replay; reusing one Candidate identity for conflicting content or
lineage also fails.

This decision supersedes ADR-0014's module-keyed pickle and path layout while
retaining its rule that failed or partial results are never cached. It refines
ADR-0022 and ADR-0026.
