## Problem Statement

The Protein Workbench frontend opens to a blank canvas. A new user has no way to see what a real multi-step protein design workflow looks like — no pre-built examples, no tutorial, no seed project. The 3GB1 conditional-design pipeline (ESM-3 → ESMFold2 → TM-score → ProteinMPNN → ESMFold2) has been built and verified end-to-end, but it lives only as a Python orchestration script (`scripts/3gb1_pipeline.py`) that cannot be viewed or interacted with through the UI.

Additionally, one step of the pipeline — pairwise TM-score evaluation of folded structures against their corresponding ESM-3 structures — cannot be expressed as a workflow DAG node because it requires a for-each pattern (fold[i] vs esm3[i]) that the workflow engine does not support.

## Solution

Three additions to make the 3GB1 pipeline a first-class default example in the UI:

1. **`structure.pairwise_align`** — a new module that accepts two `CandidateCollection`s and performs index-matched SVD alignment, outputting a `CandidateCollection` of `StructureAlignment` items. This replaces the imperative for-loop in the Python script with a single DAG-composable node.

2. **Extended `structure.batch_tm_score`** — add an optional `alignments` input port. When provided, the module skips internal SVD alignment and computes TM-score directly from the pre-computed alignments. When absent, existing behavior is unchanged (fully backward compatible).

3. **Server-side seed project** — on server startup, `ProjectManager` checks for the presence of a seed project. If absent, it creates one from a static workflow JSON file (`examples/3gb1_pipeline.json`). The project is marked `seed: true` in `project.json`. It appears in the frontend project list and can be opened and run immediately (requires configured API keys).

## User Stories

1. As a first-time user, I want to open a pre-built workflow example when I launch the app, so that I can understand what the tool is capable of without reading documentation.
2. As a first-time user, I want the example workflow to be runnable with my API keys, so that I can see protein design results immediately.
3. As a returning user, I want the seed project to never be accidentally modified or deleted through the normal UI, so that the canonical example is always available.
4. As a workflow designer, I want to express pairwise structure alignment between two candidate collections as a single DAG node, so that I can build pipelines where each folded structure is compared to its corresponding generated structure.
5. As a workflow designer, I want batch TM-score to accept pre-computed alignments, so that I can chain pairwise_align → batch_tm_score without duplicating alignment or TM-score logic.
6. As a developer, I want the seed project creation to fail gracefully (log a warning) if modules are missing or the workflow JSON is invalid, so that server startup is never blocked by example data.
7. As a developer, I want the existing `structure.batch_tm_score` behavior to be fully preserved when the new `alignments` port is absent, so that no existing workflows break.

## Implementation Decisions

### New module: `structure.pairwise_align`

- **Module ID:** `structure.pairwise_align`
- **Category:** `scoring`
- **Input ports:**
  - `reference_candidates` (type: `candidate.collection`, item_type: `protein.structure`) — the reference side (e.g., folded structures)
  - `mobile_candidates` (type: `candidate.collection`, item_type: `protein.structure`) — the mobile side (e.g., ESM-3 structures)
- **Output port:**
  - `alignments` (type: `candidate.collection`, item_type: `structure.alignment`)
- **Behavior:** Iterates over `zip(reference_candidates.items, mobile_candidates.items)`. For each pair, performs SVD superposition using Bio.SVDSuperimposer (same logic as `structure.align`). Each output `Candidate` reuses the `candidate_id` from the reference candidate so downstream scorers can correctly set `subjects`. The two input collections must have equal length; otherwise, raises `ValueError`.
- **No parameters.** Fully deterministic for given input structures.

### Modified module: `structure.batch_tm_score`

- **New optional input port:** `alignments` (type: `candidate.collection`, item_type: `structure.alignment`)
- **Behavior:**
  - If `alignments` is provided (not None): iterate over alignment candidates, compute TM-score from each alignment's RMSD and coverage using the same formula as current `structure.tm_score`. Each score entry's `subjects` is set to the alignment candidate's `candidate_id`. The `reference` and `candidates` ports are ignored.
  - If `alignments` is None or absent: existing behavior unchanged (parse reference and candidates PDBs, do SVD alignment internally, compute TM-score).
- **Backward compatibility:** The new port is optional. All existing tests, workflows, and module consumers continue to work without modification.

### Seed project mechanism

- **Seed definition file:** `examples/3gb1_pipeline.json` — a complete workflow JSON with nodes, edges, and parameters for the full 4-step pipeline. Validated at startup against the `ModuleRegistry`.
- **Project metadata:** Seed project has `"seed": true` in `project.json`. The seed project is created with a fixed, deterministic project ID (UUID derived from a namespace hash of the workflow content) so repeated restarts do not create duplicates.
- **Creation hook:** In the FastAPI lifespan handler, after `discover_modules()` and `ProjectManager` initialization, call `ProjectManager.ensure_seed_project(workflow_json_path)`. This method:
  1. Computes the deterministic project ID.
  2. Checks if `projects/<seed_id>/project.json` already exists. If yes, skip.
  3. Parses the workflow JSON, validates all `module_id` references against the registry.
  4. Creates the project directory, writes `project.json` (with `seed: true`), `workflow.json`, and `ui.json` (with default node positions).
  5. On any failure, logs a warning and continues. Does not raise.
- **No frontend changes.** Seed project appears in the existing "Open Project" list. No "Duplicate" button is added in this spec.

### Workflow JSON contents (3GB1 pipeline)

The DAG has ~16 nodes representing the complete pipeline:

1. `import.structure` → 3GB1 reference structure
2. `prompt.build_residue_layout` → layout (chain A, length 56)
3. `prompt.apply_residue_edits` → sequence track + structure track
4. `prompt.random_mask` (sequence, count=20, seed=100)
5. `prompt.random_mask` (structure, count=10, seed=102)
6. `prompt.random_insert_masked` (sequence, count=15, seed=101) → final sequence + final layout
7. `prompt.random_insert_masked` (structure, count=15, seed=101) → final structure
8. `prompt.override_residue_track` → SS track ([1,19]=E, [23,30]=H, [35,56]=E)
9. `prompt.assemble_protein_prompt` → conditioned prompt
10. `esm3.generate` (num_samples=10, seed=200) → seq_candidates + struct_candidates + scores
11. `esmfold2.fold` (candidates=seq_candidates) → folded_structures
12. `structure.batch_tm_score` (reference=3GB1, candidates=folded_structures) → tm_3gb1
13. `structure.pairwise_align` (reference_candidates=folded_structures, mobile_candidates=esm3_struct_candidates) → alignments
14. `structure.batch_tm_score` (alignments=alignments) → tm_esm3
15. `scoring.merge` (tm_3gb1 + tm_esm3) → merged_scores
16. `selection.weighted_rank` (weights: 0.7 tm_vs_3gb1 + 0.3 tm_vs_esm3) → ranked
17. `selection.top_k` (k=3) → top 3 structures
18. `prompt.random_fixed_positions` (length=56, fraction=0.5) × 3 → constraints
19. `proteinmpnn.design` (structure × 3, num_sequences=5) → 15 sequences
20. `esmfold2.fold` (candidates=15 sequences) → 15 final structures

Note: The step 3 for-each (3 structures × 5 sequences each) requires 3 parallel `prompt.random_fixed_positions` + `proteinmpnn.design` branches in the DAG. The `proteinmpnn.design` node outputs are collected via port fan-in into `esmfold2.fold`.

### Score ID renaming for weighted ranking

The `structure.batch_tm_score` outputs entries with `score_id: "tm_score"`. When merging the two TM-score sources, the score IDs must be distinct for `selection.weighted_rank` to differentiate them. An intermediate `prompt.override_residue_track`-style score renaming node, or inline renaming in the merge step, maps:
- batch_tm_score(vs 3GB1) entries → `score_id: "tm_vs_3gb1"`
- batch_tm_score(vs ESM-3) entries → `score_id: "tm_vs_esm3"`

This is handled by a lightweight approach: either a `scoring.rename` module or inline logic in the pipeline script that constructs the workflow JSON with pre-renamed score entries.

## Testing Decisions

### What makes a good test

- Tests exercise module `run()` methods through their public input/output ports, using the same `RunContext` pattern as existing module tests.
- External dependencies (Bio.SVDSuperimposer) are called directly; no mocking of the SVD algorithm itself.
- API-dependent modules (`esm3.generate`, `esmfold2.fold`, `proteinmpnn.design`) are mocked in unit tests following the existing pattern in `tests/test_esm3.py`.
- The seed project mechanism is tested via direct calls to `ProjectManager.ensure_seed_project()` with temporary directories.

### Modules to test

- **`structure.pairwise_align`:** Test equal-length collections → correct number of alignments, candidate_id preservation, RMSD for identical structures ≈ 0. Test mismatched lengths → ValueError. Test empty collections → ValueError. Test PDBs with no common residues → alignment with 0 coverage.

- **`structure.batch_tm_score` (extended):** Existing tests remain unchanged. New tests: provide `alignments` port with pre-computed alignments → verify TM-scores match expected values. Provide both `alignments` and `reference` → `alignments` takes priority (or raises). Provide `alignments` with empty items → ValueError.

- **Seed project creation:** Test that `ensure_seed_project()` creates a project directory with correct JSON files. Test that second call is idempotent. Test that invalid workflow JSON (missing module) logs warning and does not create project. Test that the deterministic project ID is stable.

### Prior art

- Module test pattern: `tests/test_scoring.py` (StructureAlign, TMScore), `tests/test_prompt_random_mask.py`
- Mock pattern for external APIs: `tests/test_esm3_unified.py` (`patch("modules.esm3_adapter.create_esm3_client")`)
- Integration test pattern: `tests/test_integration_3gb1.py`

## Out of Scope

- Frontend "Duplicate" button for seed projects. Seed project is opened read-only through the existing "Open Project" dialog.
- A general-purpose "Examples" or "Tutorials" panel in the UI. Only one seed project (3GB1) is delivered.
- `scoring.rename` as a reusable module. Score ID renaming for the weighted ranking step is handled inline in the workflow JSON construction.
- Automatic workflow JSON generation from the Python pipeline script. The JSON is hand-crafted once.
- Protection against the user deleting the seed project directory from the filesystem. The seed project is re-created on next server restart.
- Version migration for the seed project when module definitions change. The seed project is validated at creation time; stale modules result in a skipped creation (warning logged).

## Further Notes

- The seed project ID is deterministic: `uuid.uuid5(uuid.NAMESPACE_OID, json.dumps(workflow_content, sort_keys=True))`. This ensures the same workflow JSON always maps to the same project directory, preventing duplicates across restarts.
- The `ProjectManager.ensure_seed_project()` method signature: `ensure_seed_project(self, workflow_json_path: str | Path) -> ProjectMeta | None`. Returns the created (or existing) project metadata on success, `None` on failure.
- The workflow JSON for the seed project should be placed at `examples/3gb1_pipeline.json`. This file is committed to version control.
- The `examples/` directory is a peer of `scripts/` and `pdbs/`, not inside `projects/`.
