# 07 — ProteinMPNN design, score, and constraints

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

**What to build:** A user takes an imported protein structure, optionally attaches residue-level constraints (which positions are designable, which are fixed, chain selections, amino acid biases, tied positions), and runs ProteinMPNN to generate a batch of sequence candidates, each with a model confidence score. The ProteinMPNN code in `repositories/ProteinMPNN/` is never modified — a thin adapter wraps it.

**Blocked by:** 04 — Import/Export modules and 3D structure viewer.

**Status:** superseded

- [ ] ProteinMPNN adapter: thin wrapper class in `modules/proteinmpnn/adapter.py` that imports `ProteinMPNN` from `repositories/ProteinMPNN/protein_mpnn_utils.py` without modifying upstream code. Translates `ProteinStructure` (PDB string) → ProteinMPNN's expected parsed format. Translates ProteinMPNN output sequences → `ProteinSequence` objects.
- [ ] `ProteinMPNN Design` module: input = `protein.structure` (required) + `protein.sequence` (optional reference) + `proteinmpnn.constraints` (optional), output = `protein.sequence.candidates` + `score.collection`. Module parameters: model_name (enum: v_48_002, v_48_010, v_48_020, v_48_030, default v_48_020), num_sequences (int, default 1, min 1), temperature (float, default 0.1). Each generated sequence becomes a Candidate with parent lineage pointing to the input structure's candidate.
- [ ] `ProteinMPNN Score` module: input = `protein.structure` + `protein.sequence`, output = `score.collection`. Scores how well a sequence fits a structure according to ProteinMPNN's internal scoring.
- [ ] `ProteinMPNN Constraints` node: produces `proteinmpnn.constraints` type. Configurable fields: designable_positions (list of residue indices), fixed_positions, designed_chains, fixed_chains, omit_amino_acids (set of AA codes to exclude), residue_bias (per-position AA bias dict), tied_positions (list of position pairs that must have the same AA).
- [ ] UI: ProteinMPNN Constraints editor — table showing each residue with checkboxes: Designable, Fixed. Chain-level toggles. Bias editor: per-position dropdown of allowed/excluded amino acids. Tied positions: add pairs by selecting two residues.
- [ ] UI: ProteinMPNN Design node shows generation progress ("Designing sequence 12/32"). Output sequences appear in candidate list. Per-sequence ProteinMPNN scores shown alongside.
- [ ] Tests with mocked ProteinMPNN: Design produces correct number of sequence candidates. Score returns ScoreCollection with expected score ID. Constraints node produces correct data structure. Adapter translates round-trip without modifying upstream files.
