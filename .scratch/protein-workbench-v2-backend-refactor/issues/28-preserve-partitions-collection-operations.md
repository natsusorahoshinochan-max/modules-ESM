# 28 — Preserve partitions in collection operations

**What to build:** A Workflow can concatenate Candidate collections and merge Score collections while retaining exact Candidate identity and Observation source partitions, so later selectors can distinguish where every subject and score came from.

**Blocked by:** 12 — Prove the zero-Core extension journey.

**Status:** ready-for-agent

- [ ] Candidate concatenation and Score merge each have one v2 Node Definition in a single `collection_ops` package registration.
- [ ] Candidate concatenation preserves Candidate identities, parent lineage, producer/output/sample slots, stable input partitions, and deterministic ordering without minting replacement Candidates.
- [ ] Score merge preserves complete Observation identity, subject identity, Method, Context, source partition, and propagation provenance.
- [ ] Produced Observation propagation uses a controlled, versioned union/pass-through contract visible to the Compiler and does not execute arbitrary query code.
- [ ] Identical Observation identity/value may deduplicate, while conflicting values, ambiguous duplicates, invalid multiplicity, or partition collision fail closed.
- [ ] Inputs from optional collection Ports are normalized deterministically, and empty/absent collections remain distinguishable from malformed values.
- [ ] The legacy subject-free cross-Metric confidence aggregation is not migrated or silently emulated.
- [ ] Cache replay preserves collection membership and partition identity and does not copy historical scoring Invocations.
- [ ] Both operations pass CTK and public compilation/execution tests without Core collection-specific dispatch.
