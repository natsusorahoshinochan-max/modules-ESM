# 18c — 3GB1 seed workflow JSON + UI layout

**What to build:** A committed `examples/3gb1_pipeline.json` containing the complete ~20-node DAG for the 3GB1 conditional-design pipeline, plus a companion UI layout file. The JSON is validated against the `ModuleRegistry` at creation time. Nodes use accurate `module_id`, port names, and parameter schemas from the current registry. The DAG expresses: import 3GB1 → build prompt with random masks/inserts + SS track → `esm3.generate` (10 samples) → `esmfold2.fold` → dual `batch_tm_score` (one vs 3GB1, one via `pairwise_align` vs ESM-3) → `merge_scores` → `weighted_rank` (0.7/0.3) → `top_k` (k=3) → 3× `random_fixed_positions` + `proteinmpnn.design` (5 each) → final `esmfold2.fold`.

**Blocked by:** 18a, 18b — needs accurate `module_id` (`structure.pairwise_align`), port names (`alignments`), and parameter schemas (`score_id`).

**Status:** ready-for-agent

- [ ] Create `examples/` directory if absent
- [ ] `examples/3gb1_pipeline.json`: valid workflow JSON with all nodes, edges, and parameters; all `module_id` values validated against current registry
- [ ] Score differentiation: first `batch_tm_score` uses `score_id: "tm_vs_3gb1"`, second uses `score_id: "tm_vs_esm3"`
- [ ] `examples/3gb1_pipeline_ui.json`: default node positions, zoom, and viewport so the DAG displays readably on open
- [ ] Workflow is structurally identical to `scripts/3gb1_pipeline.py` logic (same seeds, same mask counts, same SS ranges, same weights)
- [ ] JSON parses correctly with `json.load()` and all module IDs resolve in registry
