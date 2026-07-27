# 02 — Preserve ProteinPrompt scientific intent at the ESM3 provider boundary

**What to build:** A protein engineer can construct and edit a ProteinPrompt knowing that every track reaches ESM3 according to its own documented semantics and final target residue layout.

**Blocked by:** 01 — Make backend verification safe, isolated, and tiered.

**Status:** ready-for-agent

- [ ] Legal amino-acid sequence symbols reach ESM3 unchanged except at explicitly masked positions.
- [ ] Secondary-structure validation accepts only the supported SS8 representation without applying that representation to another track.
- [ ] Hidden structure residues have no usable coordinates in the outbound provider payload, while visible template residues retain the documented atom representation.
- [ ] Insertions and residue mapping preserve requested absolute secondary-structure positions in the final target layout.
- [ ] Positions outside the requested E and H regions remain unspecified rather than inheriting template DSSP assignments.
- [ ] Captured provider-boundary tests prove sequence, secondary-structure, visibility, and atom fidelity without requiring a live provider call.
