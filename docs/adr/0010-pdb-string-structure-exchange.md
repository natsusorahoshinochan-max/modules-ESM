# PDB string as the unified structure exchange format

ProteinStructure carries a pdb_string field (canonical PDB text) rather than
raw coordinate arrays (numpy/torch tensors). All three providers can read and
write PDB natively: ESM SDK via to_pdb_string(), ProteinMPNN via parse_PDB(),
SimpleFold via its PDB output mode.

This eliminates the need for a custom coordinate array format and avoids
provider-specific serialization. PDB strings are self-describing (atom names,
residue identifiers, chain labels, occupancy, B-factors are all in-band).
Hashing for cache keys is straightforward: hash the PDB text directly.

Trade-off: PDB strings are larger than binary coordinate arrays and parsing
them on every read adds overhead. Accepted because protein-scale structures
(under 2000 residues) produce PDB files under 2 MB, and the simplicity gain
across three heterogeneous providers outweighs the storage and parsing cost.
