# 05 — ProteinPrompt editor

**What to build:** A user opens a dedicated ProteinPrompt editor panel, defines a target residue layout, imports a template structure to map from, and edits individual residues: insert, delete, set specific amino acids, or mask positions for the model to fill. They independently control which residues have structure coordinates visible versus which are masked. They compute DSSP and SASA from the template and optionally override values by hand. They add function annotations as named residue ranges. Finally, an "Assemble ProteinPrompt" node on the canvas collects all tracks into a single `ProteinPrompt` object ready for ESM3.

This is the most interaction-heavy part of the workbench and the critical data object that ESM3 conditions on.

**Blocked by:** 04 — Import/Export modules and 3D structure viewer.

**Status:** ready-for-agent

- [ ] `ResidueLayout` dataclass: chain ID, length. `Build Residue Layout` module: user specifies chain count and per-chain length → produces `residue.layout`.
- [ ] `ResidueMap` dataclass: source_layout, target_layout, mapping list (source residue → target residue with operation: match/insert/delete).
- [ ] `Apply Residue Edits` module: takes template ProteinStructure + ResidueLayout + edit operations → produces updated ProteinPrompt with per-residue tracks. Supported edits: Insert (create new target position), Delete (remove target position), Set Residue (specify amino acid), Mask Residue (leave for model).
- [ ] Per-residue tracks in ProteinPrompt, each an array of length = target layout length: sequence track (amino acid or unspecified), structure coordinate track (xyz or masked), structure visibility track (boolean per residue), secondary structure track (DSSP code or unspecified), SASA track (float or unspecified).
- [ ] Tracks are fully independent: changing sequence at position 5 does not affect structure visibility at position 5.
- [ ] `Compute Secondary Structure` module: takes ProteinStructure → calls mkdssp subprocess → produces `residue.track.secondary_structure`.
- [ ] `Compute SASA` module: takes ProteinStructure → computes per-residue SASA → produces `residue.track.sasa`.
- [ ] `Override Residue Track` module: takes a track + manual edits → produces updated track. Allows hand-editing any computed track.
- [ ] `Add Function Annotation` module: takes label, start, end → adds to function annotations list.
- [ ] `Assemble ProteinPrompt` node: takes residue layout + sequence track + structure track + visibility track + secondary structure track + SASA track + function annotations → produces a complete `protein.prompt`.
- [ ] UI: ProteinPrompt editor panel — table view with one row per residue, columns for: residue index, chain, amino acid (editable dropdown or "masked"), structure visible (checkbox), secondary structure (dropdown: H/B/E/G/I/T/S/-/unspecified), SASA (numeric input or unspecified). Toolbar buttons: Insert Before, Insert After, Delete Selected, Mask Selected, Set All To.
- [ ] UI: structure visibility selector — interactive 3D viewer integration where clicking residues toggles visibility, synced bidirectionally with the table.
- [ ] UI: function annotation editor — list of named ranges with add/remove/edit.
- [ ] Tests: Build Residue Layout produces correct chain/length. Apply Residue Edits: insert increases length, delete decreases, set changes amino acid, mask sets unspecified. Track independence: change sequence, verify structure visibility unchanged. DSSP computation matches known reference output. Assemble ProteinPrompt rejects mismatched track lengths.
