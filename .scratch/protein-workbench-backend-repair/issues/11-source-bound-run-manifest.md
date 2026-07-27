# 11 — Persist a source-bound run manifest and Cache provenance

**What to build:** Every run has one durable, atomically updated manifest that binds its scientific outputs and Cache decisions to the source, Workflow, environment, providers, and effective seeds that produced them.

**Blocked by:** 10 — Contain every project and run in an isolated storage namespace.

**Status:** completed

- [x] A manifest is created before Node execution and updated atomically through a terminal run state.
- [x] The manifest records source revision and dirty state, Workflow hash, project/run IDs, ModuleDefinition versions, effective seeds, and environment/model identity.
- [x] Provider readiness and actual provider calls are recorded as separate facts.
- [x] Ordered Node states, structured failures, Cache hits/misses, Candidate lineage, artifact references, sizes, and hashes can be recorded without importing historical evidence.
- [x] Cache parameter normalization is recursive, so semantically identical parameters produce the same identity regardless of dictionary insertion order.
- [x] Failed or partial Node outputs are never cached, while every successful Cache use is attributed to the consuming run.
- [x] Secrets and credentials are redacted from manifests, logs, diagnostics, fixtures, and retained evidence.
