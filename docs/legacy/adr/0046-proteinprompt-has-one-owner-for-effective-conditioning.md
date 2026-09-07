---
status: accepted
---

# ProteinPrompt has one owner for each effective conditioning value

`ProteinPrompt` retains one identity-complete residue layout and aligned
sequence, structure-coordinate, secondary-structure, absolute-SASA, and
function-annotation values. Sequence and structure are always present nullable
tracks; an all-null track is their sole fully masked representation. A concrete
structure value is the sole owner of the Prompt-side named-atom coordinates,
while a null value means that residue supplies no Prompt-side coordinates.
Provider Adapters translate only their provider-visible subset. For ESM-3
structure conditioning, only the atom37 projection affects the provider call
and functional-input digest; non-atom37 atoms remain in ProteinPrompt but are
provider-invisible.
Viewer hide/show state is opaque UI state and never a scientific Prompt track.

Function annotations retain only the label, one-based inclusive interval, and
chain-qualified endpoint provenance needed to interpret and reattach them.
Whether intervals may overlap is an authoring-operation parameter applied to
the resulting collection, not annotation content. ESM-3 call randomness is
scoped to the exact translated sequence, coordinates, secondary structure,
absolute SASA, and provider annotation values plus the sample/track slot; layout
labels, authoring policies, and other provider-invisible provenance do not alter
the random stream.

Secondary-structure and SASA tracks remain optional because their absent and
all-null provider forms have not been established as scientifically equivalent.
Every present track remains aligned to the target layout. Concrete SASA values
remain absolute per-residue solvent-accessible surface areas in square
angstroms without normalization.

This decision supersedes ADR-0004.
