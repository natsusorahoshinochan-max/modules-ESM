# 05 — Produce standard reference-normalized TM-scores

**What to build:** A protein engineer receives standard per-residue TM-scores derived from the shared StructureAlignment, with explicit normalization and coverage semantics suitable for comparing Candidates against 3GB1.

**Blocked by:** 04 — Expand StructureAlignment into reproducible correspondence evidence.

**Status:** completed

- [x] TM-score is calculated from aligned per-residue distances rather than from one global RMSD.
- [x] The normalization length is explicit, and the 3GB1 objective uses reference normalization.
- [x] A perfectly aligned fragment receives credit proportional to reference coverage rather than a perfect full-reference score.
- [x] Single and collection scoring paths share the same scientifically valid alignment and TM-score semantics.
- [x] Differential tests agree with a trusted structural-alignment implementation for identical structures, outliers, partial coverage, insertions, deletions, renumbering, and chain changes.
- [x] RMSD remains derivable from the shared StructureAlignment without independently reconstructing residue correspondence.
