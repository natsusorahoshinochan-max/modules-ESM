# 18b — Extend `structure.batch_tm_score` with alignment input + score_id parameter

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

**What to build:** `structure.batch_tm_score` gains an optional `alignments` input port and a `score_id` parameter. When `alignments` is provided, the module skips internal SVD alignment and computes TM-score directly from pre-computed `StructureAlignment` items — using the same TM-score formula as `structure.tm_score`. The `score_id` parameter (default `"tm_score"`) lets the user set the output score identifier, so two batch_tm_score instances in the same DAG (one vs 3GB1, one vs ESM-3) emit distinguishable entries (`"tm_vs_3gb1"`, `"tm_vs_esm3"`). When `alignments` is absent, existing behavior is fully preserved.

**Blocked by:** 18a — test alignments benefit from having `pairwise_align` available for realistic data.

**Status:** superseded

- [ ] Add optional `alignments` input port (type: `candidate.collection`, item_type: `structure.alignment`) to `definition.yaml`
- [ ] Add `score_id` parameter (type: `string`, default: `"tm_score"`) to `definition.yaml`
- [ ] Alignment path in `module.py`: when `alignments` is provided, iterate alignment candidates and compute TM-score from `alignment.rmsd` and `alignment.coverage` using existing TM formula; set subjects from alignment `candidate_id`; ignore `reference` and `candidates` ports
- [ ] Use `score_id` parameter value for all output `Score.score_id` entries (both alignment path and existing reference+candidates path)
- [ ] Existing path unchanged when `alignments` is absent: validate `reference` + `candidates`, do SVD internally, use `score_id` parameter for output entries
- [ ] Backward compatibility: all existing tests pass without modification (parameter defaults to `"tm_score"`)
- [ ] New tests: provide `alignments` → correct TM-scores; empty alignments → ValueError; alignments port takes priority over reference; custom `score_id` → correct output score_id; `alignments` with no common residues → score 0
- [ ] Hardcoded module count assertions unchanged (no new module)
