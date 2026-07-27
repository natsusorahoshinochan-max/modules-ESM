# 15 — Give the canonical 3GB1 seed a stable, protected identity

**What to build:** New and existing backend clients see one validated canonical 3GB1 example whose identity survives content upgrades and whose accepted content cannot be mutated through ordinary project writes.

**Blocked by:** 02 — Preserve ProteinPrompt scientific intent at the ESM3 provider boundary; 08 — Generate reproducible ProteinMPNN children per selected parent; 10 — Contain every project and run in an isolated storage namespace.

**Status:** ready-for-agent

- [ ] The canonical seed uses a stable semantic identity independent of its serialized content hash.
- [ ] Startup validates the shipped Workflow against current ModuleDefinitions, Port types, and graph rules and fails visibly on drift.
- [ ] Missing or drifted canonical content is restored or upgraded atomically without changing canonical identity.
- [ ] Ordinary Workflow and metadata writes to the canonical seed are rejected by the backend.
- [ ] Legacy or user-modified seed projects are preserved as ordinary or clearly marked legacy projects and do not retain canonical status.
- [ ] Repeated startup creates neither duplicate canonical projects nor multiple projects claiming canonical status.
