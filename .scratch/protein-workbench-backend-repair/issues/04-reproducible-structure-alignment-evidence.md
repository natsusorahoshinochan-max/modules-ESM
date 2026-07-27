# 04 — Expand StructureAlignment into reproducible correspondence evidence

**What to build:** A structure comparison produces a public StructureAlignment containing enough sequence-aware correspondence and per-residue evidence for downstream scorers to reproduce RMSD, coverage, and standard TM-score.

**Blocked by:** 01 — Make backend verification safe, isolated, and tiered.

**Status:** completed

- [x] Residue correspondence is sequence-aware and remains correct across insertions, deletions, residue renumbering, and chain-label changes.
- [x] PDB residue and chain labels remain available as provenance but are not the sole matching key.
- [x] StructureAlignment exposes the aligned reference/mobile correspondence, normalization-relevant lengths, coordinates or distances, transformation, RMSD, and coverage.
- [x] Existing valid alignment consumers remain green while the public alignment contract is expanded.
- [x] Identical, shifted, partially covered, inserted, deleted, renumbered, and chain-changed examples produce reproducible public alignment evidence.
