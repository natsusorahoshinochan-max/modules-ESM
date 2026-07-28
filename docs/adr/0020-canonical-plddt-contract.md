---
status: accepted
---

# Public pLDDT uses canonical 0–100 Metrics

Protein Workbench exposes pLDDT as two dimensionless, higher-is-better Metrics:
`structure.plddt.per_residue` and `structure.plddt.mean_residue`, both with the
canonical range `[0, 100]`. The scalar Metric is the arithmetic mean of valid
protein residues with equal residue weight, excluding padding, chain breaks,
non-protein tokens, and NaN values.

Each Adapter has a static native-scale contract and performs one explicit
normalization: current ESM-3 and ESMFold2 public values are multiplied by 100,
the SimpleFold high-level wrapper is already on the canonical scale, and direct
SimpleFold confidence-head values are multiplied by 100. Range guessing such
as `max(values) <= 1` is forbidden. Structure serialization continues to obey
the provider-native scale so canonical values are never scaled twice.

The Method records the actual model and confidence-head identity. pTM remains
on `[0, 1]`, PAE remains measured in angstroms, and classic Meta ESMFold is
outside the project scope.
