---
status: accepted
---

# Workflow composition preserves residue identity and Candidate lineage

Workflow usability repairs must preserve the existing exact nominal type
system. A raw scientific value is not implicitly interchangeable with a
Candidate Collection, a Workbench ResidueIdentity is not a provider position,
and a modified polymer component is not silently omitted or renamed.

Candidate-producing transformations therefore expose Candidate-aware Node
Types. Structure-to-sequence extraction and chain selection create one child
per input parent and record that exact parent identity. FASTA import publishes
both the raw sequence and its singleton root Candidate Collection. Pairwise
sibling mapping is created only when each subject and reference has exactly one
shared parent; collection order is not scientific correspondence.

ProteinMPNN constraints use stable identities from an identity-complete
`ResidueLayout` for fixed, designable, tied, and biased residues. The Adapter is
the only seam that converts those identities to upstream one-based positions.
It validates parsed chain order and cardinality, labels returned sequences with
the Workbench layout, and persists the complete identity-to-provider-position
mapping in Candidate provenance. Positional integers are not accepted as a
compatibility form. ProteinMPNN's geometric validity mask is not a sequence
layout mask: a fixed residue without a complete backbone is restored from the
provider input in the complete output layout, while requesting design at such
a residue fails closed.

The repository-owned CSH normalization is an explicit scientific
transformation. It accepts only the locked, unambiguous 19-atom CSH inventory,
expands it to the `SER-HIS-GLY` parent span at observed numbering minus one,
observed numbering, and observed numbering plus one, and emits a typed
component/parent/atom mapping. Missing atoms, extra atoms, alternate locations,
insertion-coded components, or parent-identity collisions fail closed. The
original Project Input remains unchanged, and direct structure-to-Prompt
conversion continues to reject unnormalized CSH.

`build_residue_layout` remains canonical-only. Deterministic gap authoring uses
a whole-Prompt insertion Node addressed by adjacent source identities and
explicit inserted identities. It preserves every source identity and present
track value, inserts `null` on every present track, remaps annotation positions,
and emits a complete match/insert-only `ResidueMap`.

Scientific provider seeds bind to the configured seed, parent structure
content, and stable parent slot. Candidate Result Identity remains execution
provenance and cannot perturb a scientific random draw when the exact structure
content and slot are unchanged.

Changing any of these lineage, residue-identity, normalization, mapping,
editing, or seed contracts requires new versioned public contracts. This
decision refines ADR-0003, ADR-0028, and ADR-0031.
