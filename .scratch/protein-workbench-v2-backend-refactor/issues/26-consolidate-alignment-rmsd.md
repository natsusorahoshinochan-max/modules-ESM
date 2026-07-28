# 26 — Consolidate alignment and RMSD

**What to build:** A Workflow can align one structure pair or corresponding Candidate collections and compute RMSD from explicit reproducible correspondence evidence through one `structure_comparison` Module Package.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** ready-for-agent

- [ ] Single alignment, pairwise collection alignment, and RMSD each have one v2 Node Definition in a single package registration.
- [ ] Alignment output is a versioned nominal value that records exact subject/reference Candidate identities and content digests, residue/atom correspondence, transformation, normalization inputs, and method identity.
- [ ] Input role semantics remain explicit regardless of the underlying library's reference/mobile call ordering.
- [ ] Pairwise collection alignment defines its accepted cardinality and pairing source rather than relying on collection order, free-form Candidate IDs, or lineage guessing.
- [ ] RMSD is emitted as a declared pairwise Metric/Method/Context Observation and cannot accept a mutable `candidate_id` or anonymous alignment.
- [ ] The package records a composite Operation separately from any nested alignment engine Invocations and represents their true parent-child relationship.
- [ ] Incomplete correspondence, incompatible structures, empty selections, invalid transformations, non-finite values, and conflicting identities fail before output or Cache publication.
- [ ] Deterministic fixtures prove exact correspondence evidence, role orientation, multi-Candidate behavior, Cache replay, and failure isolation.
- [ ] All Nodes pass CTK and installed discovery without duplicate alignment adapters, Definitions, or Core scoring logic.
