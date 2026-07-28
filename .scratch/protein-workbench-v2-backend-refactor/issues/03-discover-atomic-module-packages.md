# 03 — Discover atomic Module Packages

**What to build:** A repository maintainer can add one explicit Module Package registration and have its public contracts and Binding Availability appear atomically in the same FrozenCatalog consumed by the v2 public Catalog Snapshot, without adding Core dispatch logic.

**Blocked by:** 02 — Publish canonical nominal Port Types.

**Status:** ready-for-agent

- [ ] One immutable Module Package registration can explicitly contribute Node and Metric resources, Methods, Bindings, Port Types, Utility Transforms, lazy factories, and Availability/Readiness declarations.
- [ ] Startup discovery reads only first-level Module Packages through their single production registration and does not use recursive Definition scans, globs, helper enumeration, per-Node registration, or import side effects.
- [ ] Package import remains safe when optional provider dependencies are absent; each affected Binding remains queryable with a structured unavailable reason and does not hide an available sibling.
- [ ] Catalog construction validates closed schemas, resource ownership, exact references, versions, canonical digests, duplicate identities, conflicts, dangling references, and cycles before publication.
- [ ] Construction occurs in temporary state and publishes one immutable FrozenCatalog only after every package succeeds; every failure leaves no partial Catalog visible.
- [ ] Node, Metric, Method, Binding, and Utility descriptors follow the same canonical byte rules and use explicit behavior identities for factories, probes, adapters, observation propagation, and transforms.
- [ ] Catalog Snapshot separates stable contract identity from observed Binding Availability identity and observation time.
- [ ] A conforming synthetic registration proves discovery and public query without becoming a production scientific capability.
