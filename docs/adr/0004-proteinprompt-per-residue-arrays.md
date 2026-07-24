# ProteinPrompt uses per-residue arrays with optional values

Each track in ProteinPrompt stores an array of length equal to the target layout,
where each position holds either a concrete value or a sentinel meaning unspecified
/ masked / not visible. The tracks are fully independent: sequence specification,
structure visibility, secondary structure status, and SASA status each have their
own array.

The alternative was a compressed representation: one bitmask per track indicating
which positions are specified, plus a packed array of only the specified values.
Rejected because insertions and deletions would require shifting both the bitmask
and the packed array, adding index bookkeeping complexity for no meaningful benefit
at protein-scale lengths (typically under 2000 residues).
