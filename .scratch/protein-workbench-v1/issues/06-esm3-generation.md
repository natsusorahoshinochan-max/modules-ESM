# 06 — ESM3 sequence and structure generation

**What to build:** A user takes an assembled ProteinPrompt, runs ESM3 Generate Sequence to get a batch of candidate sequences, picks the best one, updates the prompt's sequence track while keeping all other tracks intact, then runs ESM3 Generate Structure to obtain 3D coordinates. They see each candidate's confidence scores and can inspect the generated structures in the 3D viewer.

This is the primary design workflow and the most complex provider integration. The ESM3 adapter translates between the workbench's public types and the ESM SDK's `ESMProtein` format.

**Blocked by:** 05 — ProteinPrompt editor.

**Status:** ready-for-agent

- [ ] ESM3 adapter: translates `ProteinPrompt` → ESM SDK `ESMProtein`. Maps per-residue tracks: sequence → ESMProtein.sequence, structure coordinates → ESMProtein.coordinates (with masked positions as NaN), secondary structure → ESMProtein.secondary_structure, SASA → ESMProtein.sasa. Maps function annotations to ESMProtein.function_annotations.
- [ ] `ESM3 Generate Sequence` module: input = `protein.prompt`, output = `protein.sequence.candidates` + `score.collection`. Module parameters: model_name (enum: esm3-medium-2024-08, esm3-open-2024-03), num_steps, temperature, top_p, track (fixed to "sequence"). Calls ESM SDK `generate(track="sequence")`. Produces one Candidate per generated sequence, each with parent lineage pointing to the prompt's source candidate.
- [ ] Generation output classification for sequence-only: since no coordinates are in the prompt, structure in the generation result must be classified as `absent`. The module must not emit spurious structure data just because the SDK response type can carry it.
- [ ] `Update Prompt Sequence` module: input = `protein.prompt` + `protein.sequence`, output = `protein.prompt`. Replaces the sequence track with the provided sequence. All other tracks (structure coordinates, visibility, secondary structure, SASA, annotations) pass through unchanged.
- [ ] `ESM3 Generate Structure` module: input = `protein.prompt`, output = `protein.structure.candidates` + `score.collection`. Module parameters: model_name, num_steps, temperature, top_p, track (fixed to "structure"). Calls ESM SDK `generate(track="structure")`.
- [ ] Generation output classification for structure: if prompt had no coordinates → structure `absent`. If prompt had template coordinates (Direct mode) → `prompt_reconstruction` with Source Structure binding. If Guided mode → `sampled_structure` only for the terminal denoise structure.
- [ ] Structure metric normalization: pTM → dimensionless scalar (handles `(1,)`→scalar). PAE → `(L,L)` matrix (handles `(1,L+2,L+2)`→`(L,L)` by stripping batch axis and special tokens). No generic squeeze — unknown shapes fail closed.
- [ ] Candidate lineage: each generated sequence candidate's parent is the prompt's source. Each generated structure candidate's parent is the sequence candidate used to update the prompt.
- [ ] REST API: execution triggers all three modules in sequence when the workflow is run. WebSocket pushes per-candidate generation progress.
- [ ] UI: node displays generation progress (e.g., "Generating sequence 5/32"). Candidates appear in a candidate list panel. Clicking a sequence candidate shows its sequence and scores. Clicking a structure candidate updates the 3D viewer.
- [ ] Tests with mocked ESM SDK: Generate Sequence produces correct number of candidates. Update Prompt Sequence preserves non-sequence tracks. Generate Structure produces ProteinStructure with valid PDB. Output classification is correct for Direct-no-coordinates (absent), Direct-with-coordinates (prompt_reconstruction), Guided (sampled_structure). pTM and PAE normalization handles all known shapes.
- [ ] Key management: Biohub token read from `keys/esmkey.txt` at module init. Hugging Face token for local open-weight model (`esm3_sm_open_v1`) read from `keys/huggingfacekey.txt`. Keys are never logged, serialized, or exposed through the API. Missing key file produces a clear error message at node execution time (not startup crash).
