# Define structure and sequence fidelity at public boundaries

Type: grilling
Mode: HITL
Status: open
Blocked by: 01

## Question

For PDB, FASTA, Residue Layout, structure annotation, and
structure-to-sequence conversion, which valid upstream semantics must be
preserved and which malformed cases must fail before execution? Resolve
multi-record FASTA, negative and non-contiguous residue identifiers, internal
insertions, alternate locations, contradictory residue names, DSSP coil/PPII,
missing residues, and SASA nullability as one coherent public-boundary policy.
