# 09 — Scoring: alignment, metrics, DSSP, and agreement

**What to build:** A user compares two protein structures — the ESM3-generated structure and a SimpleFold-folded structure, or any pair of structures in the workflow. They compute a structure alignment, then derive TM-score and RMSD from that alignment. They also compute DSSP secondary structure from a folded structure and compare it against their target secondary structure specification to get an agreement score. Multiple score outputs can be merged into a single ScoreCollection for downstream selection.

**Blocked by:** 04 — Import/Export modules and 3D structure viewer, and 08 — Folding: ESMFold2 and SimpleFold.

**Status:** ready-for-agent

- [ ] `Structure Alignment` module: input = `protein.structure` (reference) + `protein.structure` (mobile), output = `structure.alignment`. Uses Bio.SVDSuperimposer. Produces: residue mapping (reference residue → mobile residue), chain mapping, rotation matrix, translation vector, RMSD, coverage (number of aligned residues / total). The alignment is reusable by downstream scorers.
- [ ] `TM-score` module: input = `structure.alignment`, output = `score.collection`. Uses tmtools.tm_align with the pre-computed alignment. Score entry includes: tm_score value, aligned_residues count, normalization type (reference).
- [ ] `RMSD` module: input = `structure.alignment`, output = `score.collection`. Reads the RMSD field directly from the StructureAlignment. Score entry includes: rmsd value in angstroms, aligned_residues count.
- [ ] `DSSP` module: input = `protein.structure`, output = `residue.track.secondary_structure`. Calls mkdssp subprocess (v4.6.1 at `/opt/homebrew/bin/mkdssp`), parses output, produces per-residue DSSP codes.
- [ ] `Secondary Structure Agreement` module: input = `residue.track.secondary_structure` (expected) + `residue.track.secondary_structure` (observed), output = `score.collection`. Score entries include: overlap fraction, compared residue count, coverage, per-residue match boolean array.
- [ ] `Aggregate Confidence` module: input = `score.collection`, output = `score.collection`. Aggregates multiple per-residue or per-candidate confidence scores (e.g., pLDDT) into summary statistics: mean, median, min, max.
- [ ] `Merge Scores` module: input = one or more `score.collection` ports, output = a single `score.collection`. Concatenates score entries from all inputs, preserving score IDs and subject references. No weighting or aggregation — pure concatenation.
- [ ] UI: score viewer panel — table of score entries with columns: Score ID, Value, Subjects, Details (expandable). Filterable by score ID. Sortable by value.
- [ ] UI: alignment visualization — when a StructureAlignment is produced, the 3D viewer shows both structures superposed with the mobile structure in a distinct color.
- [ ] UI: secondary structure comparison view — side-by-side bar chart or track visualization showing expected vs observed DSSP per residue, with mismatches highlighted.
- [ ] Tests: Structure Alignment produces valid superposition for known structure pair. TM-score and RMSD match expected values for a known reference case (e.g., 1PGA vs itself = TM 1.0, RMSD 0.0). DSSP output matches known reference. Secondary Structure Agreement: identical tracks = 1.0 overlap. Merge Scores concatenates correctly. Aggregate Confidence computes correct mean/median.
