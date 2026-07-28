---
status: accepted
---

# v2 is a pre-release breaking contract reset

Protein Workbench has not been deployed or used in production, so v2 is the
only supported runtime contract rather than a backward-compatible migration
target. The project will not implement a v1 Workflow migrator, legacy Score
aliases, dual-format readers, pLDDT auto-conversion, or compatibility reuse of
v1 caches and manifests.

Local projects, caches, and run records are disposable development state and
will be cleared and regenerated at cutover. Repository-owned examples, seed
Workflows, and test fixtures will instead be rewritten directly to v2. Workflow
documents become self-identifying with a top-level v2 schema version, run
manifests use the v2 schema, and caches use a global v2 namespace in addition
to Node Type versions.

The global Cache namespace means one schema namespace,
`protein-workbench-cache/v2`; it does not authorize immediate cross-Project
physical sharing. Initial v2 Cache storage remains Project-scoped as defined by
ADR-0031. Physical deletion of development state is a separately authorized
cutover action, not an automatic consequence of accepting this ADR.

An old runtime artifact fails with a structured
`unsupported_schema_version` error; it is never guessed, converted, or silently
reinterpreted. Historical v1 specifications and ADRs may remain as design
provenance but do not create runtime compatibility obligations.
