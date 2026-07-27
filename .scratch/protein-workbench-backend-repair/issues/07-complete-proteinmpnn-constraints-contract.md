# 07 — Enforce the complete ProteinMPNN constraints contract

**What to build:** ProteinMPNN honors every supported public constraint through one documented zero-based indexing contract and rejects malformed or unsupported constraints before inference.

**Blocked by:** 01 — Make backend verification safe, isolated, and tiered.

**Status:** ready-for-agent

- [ ] Public residue positions are zero-based target-layout indices and are converted to upstream chain-qualified positions exactly once.
- [ ] First- and last-residue fixed-position tests prove there is no off-by-one or negative-index behavior.
- [ ] Designable positions, fixed positions, designed/fixed chains, tied positions, omit rules, and residue-specific amino-acid biases are translated completely.
- [ ] Multi-chain chain and residue references are validated before inference with actionable errors.
- [ ] Structure and reference-sequence lengths must match exactly; padding and truncation are rejected.
- [ ] The optional reference-sequence input is honored according to its public Port contract or removed through an explicit Module version change.
- [ ] Backbone noise and sampling controls are explicit Module parameters with documented defaults.
