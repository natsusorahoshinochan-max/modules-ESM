# 07 — Enforce the complete ProteinMPNN constraints contract

**What to build:** ProteinMPNN honors every supported public constraint through one documented zero-based indexing contract and rejects malformed or unsupported constraints before inference.

**Blocked by:** 01 — Make backend verification safe, isolated, and tiered.

**Status:** completed

- [x] Public residue positions are zero-based target-layout indices and are converted to upstream chain-qualified positions exactly once.
- [x] First- and last-residue fixed-position tests prove there is no off-by-one or negative-index behavior.
- [x] Designable positions, fixed positions, designed/fixed chains, tied positions, omit rules, and residue-specific amino-acid biases are translated completely.
- [x] Multi-chain chain and residue references are validated before inference with actionable errors.
- [x] Structure and reference-sequence lengths must match exactly; padding and truncation are rejected.
- [x] The optional reference-sequence input is honored according to its public Port contract or removed through an explicit Module version change.
- [x] Backbone noise and sampling controls are explicit Module parameters with documented defaults.
