# 20 — Seal a fresh remote-real 3GB1 acceptance run

**What to build:** An acceptance operator executes one fresh canonical 3GB1 backend run against the required real providers and seals enough source-bound evidence to authorize a separate frontend-rewrite specification.

**Blocked by:** 19 — Run required real-provider gates without green skips.

**Status:** completed — the source-bound `fresh-remote-3gb1` operator requires
one clean, isolated, force-rerun canonical backend execution and seals its
validated REST/WebSocket/provider/artifact evidence without frontend work.

- [x] The run is started from the current canonical Workflow through the backend REST API and followed through its run-scoped WebSocket stream.
- [x] The sealed manifest identifies the exact source revision and dirty state, Workflow hash, ModuleDefinition versions, environment, providers, actual calls, effective seeds, Cache decisions, and ordered Node outcomes.
- [x] The run produces ten paired ESM3 Candidates, the expected scoring and top-three selection, three parents with five ProteinMPNN children each, and fifteen final structures.
- [x] Exactly fifteen nonempty PDB artifacts are retrieved by run ID and independently match the manifest paths, sizes, hashes, and complete lineage.
- [x] The dated bundle contains the immutable manifest, JUnit results, command transcript, environment summary, and artifact checksums with all secrets redacted.
- [x] No historical Cache entry or historical PDB is represented as evidence produced by this fresh run.
- [x] The sealed bundle is sufficient to freeze the corrected backend contracts without modifying or testing the current React frontend.

Final completion evidence must be produced by running the full tier from this
ticket's final clean commit. Diagnostic runs from a dirty checkout cannot satisfy
the ticket.
