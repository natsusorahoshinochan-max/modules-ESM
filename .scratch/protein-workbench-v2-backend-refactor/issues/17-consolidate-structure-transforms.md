# 17 — Consolidate structure transforms

**What to build:** A Workflow can select chains, extract a backbone, or derive a sequence from a structure through explicit, provenance-bearing scientific conversion Nodes in one `structure_transform` Module Package.

**Blocked by:** 13 — Consolidate protein I/O.

**Status:** ready-for-agent

- [ ] Chain selection, backbone extraction, and sequence extraction each have one independent v2 Node Definition and share one cohesive package registration.
- [ ] Exact nominal input/output Port Types make every conversion visible in the Workflow and prevent implicit structure-to-sequence or full-atom-to-backbone coercion.
- [ ] Chain selection validates requested chain identities, deterministic ordering, empty results, duplicated requests, and multi-model behavior.
- [ ] Backbone extraction defines and validates retained atoms, residues, chain breaks, alternate locations, missing atoms, and content identity.
- [ ] Sequence extraction defines treatment of non-protein residues, unknown residues, chain separation, and residue-to-sequence correspondence.
- [ ] Every output is canonical, content-digested, and carries producer/output lineage suitable for Result Identity and Candidate derivation.
- [ ] Import-transform-export public journeys prove that artifacts stay Run-bound and that no private path crosses a Port or enters scientific identity.
- [ ] The package removes duplicated conversion registration/Definition glue and passes the common CTK without Core type or dispatch edits.
