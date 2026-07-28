# 14 — Consolidate residue layout and track editing

**What to build:** A Workflow author can build a residue layout, apply explicit residue edits, map tracks between layouts, and override selected residues through one coherent `prompt_authoring` contract whose per-residue values remain aligned and scientifically interpretable.

**Blocked by:** 12 — Prove the zero-Core extension journey.

**Status:** ready-for-agent

- [ ] Layout construction, residue editing, track mapping, and track override each have one independent v2 Node Definition under one `prompt_authoring` registration.
- [ ] Shared implementation and domain values replace duplicated per-directory Definition loading, registration glue, and ad hoc track parsing.
- [ ] Every per-residue track is validated against the target layout, chain boundaries, residue identities, visibility, and nullable-value semantics before publication.
- [ ] Residue edits preserve an explicit source-to-target residue map and reject overlaps, out-of-range edits, contradictory chain operations, and length drift.
- [ ] Track mapping is an explicit scientific conversion Node with provenance; nominally different tracks are never connected through structural similarity or an implicit coercion.
- [ ] Overrides distinguish clearing, preserving, and replacing values and never silently shift downstream residue indices.
- [ ] Deterministic inputs produce canonical outputs and stable Result Identities without provider, credential, or environment dependence.
- [ ] Differential fixtures cover insertion/deletion boundaries, chain breaks, unmapped residues, optional values, and the accepted secondary-structure layout-shift regression.
- [ ] The package slice compiles and executes through the shared CTK and public protocol without Core dispatch changes.
