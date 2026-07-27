# 20 — Seal a fresh remote-real 3GB1 acceptance run

**What to build:** An acceptance operator executes one fresh canonical 3GB1 backend run against the required real providers and seals enough source-bound evidence to authorize a separate frontend-rewrite specification.

**Blocked by:** 19 — Run required real-provider gates without green skips.

**Status:** ready-for-agent

- [ ] The run is started from the current canonical Workflow through the backend REST API and followed through its run-scoped WebSocket stream.
- [ ] The sealed manifest identifies the exact source revision and dirty state, Workflow hash, ModuleDefinition versions, environment, providers, actual calls, effective seeds, Cache decisions, and ordered Node outcomes.
- [ ] The run produces ten paired ESM3 Candidates, the expected scoring and top-three selection, three parents with five ProteinMPNN children each, and fifteen final structures.
- [ ] Exactly fifteen nonempty PDB artifacts are retrieved by run ID and independently match the manifest paths, sizes, hashes, and complete lineage.
- [ ] The dated bundle contains the immutable manifest, JUnit results, command transcript, environment summary, and artifact checksums with all secrets redacted.
- [ ] No historical Cache entry or historical PDB is represented as evidence produced by this fresh run.
- [ ] The sealed bundle is sufficient to freeze the corrected backend contracts without modifying or testing the current React frontend.
