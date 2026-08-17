# 08 — Folding: ESMFold2 and SimpleFold

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

**What to build:** A user takes sequence candidates (from ESM3 or ProteinMPNN) and folds them into 3D structures using two independent folding backends — ESMFold2 for accurate single-chain prediction and SimpleFold for fast batch screening with optional re-scoring. Each folded structure carries lineage back to its sequence parent. The user can compare folds from the same sequence across both backends.

**Blocked by:** 06 — ESM3 sequence and structure generation, and 07 — ProteinMPNN design, score, and constraints.

**Status:** superseded

- [ ] ESMFold2 adapter: translates `ProteinSequence` → Biohub `/fold` request. Strict single-chain contract: exactly one `/fold` call per request. Optional controls: `include_pae` (bool), `include_embeddings` (bool). Distogram is not requested. `/fold_all_atom` is never used.
- [ ] ESMFold2 adapter response parsing: extracts structure coordinates, pLDDT, pTM from response. When `include_pae=true`, extracts PAE. When `include_embeddings=true`, extracts `embedding_pair_pooled` (only; `embedding_sequence` is not guaranteed and not exposed). Handles SDK 3.3.0 `to_pdb_string()` rendering defect by using `to_protein_chain()` single-chain view with oxygen completion.
- [ ] `ESMFold2 Fold` module: input = `protein.sequence` or `protein.sequence.candidates`, output = `protein.structure.candidates` + `score.collection` (pLDDT, pTM, PAE). Module parameters: model_name (enum: esmfold2-fast-2026-05, esmfold2-2026-05), include_pae (bool), include_embeddings (bool).
- [ ] SimpleFold adapter: translates `ProteinSequence` → FASTA (internal temp file) → calls SimpleFold CLI → parses output PDB/mmCIF → `ProteinStructure`. Translates `ProteinStructure` → calls SimpleFold evaluate → parses pLDDT scores.
- [ ] `SimpleFold Fold` module: input = `protein.sequence` or `protein.sequence.candidates`, output = `protein.structure.candidates` + `score.collection` (pLDDT from forward pass). Module parameters: num_steps (int, capped at 50). Uses 100M model.
- [ ] `SimpleFold Evaluate` module: input = `protein.structure` or `protein.structure.candidates`, output = `score.collection` (pLDDT). No re-folding — runs only the pLDDT head on existing structures. Uses larger model (360M default; configurable).
- [ ] Candidate lineage: each folded structure candidate has `parent_ids` pointing to the input sequence candidate. This enables traceback: ESM3 candidate → ProteinMPNN candidate → ESMFold2 fold → SimpleFold fold.
- [ ] When input is a `CandidateCollection`, the module processes each candidate independently, producing one `CandidateCollection` of folded structures with individual parent references preserved.
- [ ] UI: fold node shows per-candidate progress ("Folding candidate 3/32"). Folded structures appear in candidate list grouped under their sequence parent. 3D viewer updates when a folded structure candidate is selected.
- [ ] UI: side-by-side structure comparison — select two structure candidates to view them overlaid in the 3D viewer with different colors.
- [ ] Tests with mocked providers: ESMFold2 produces ProteinStructure with pLDDT/pTM for each input sequence. PAE extraction produces (L,L) matrix. Embeddings extraction produces pair_pooled only. SimpleFold Fold produces structures; Evaluate produces scores without re-folding. Candidate lineage preserved through fold step. Input as single sequence vs CandidateCollection both handled.
- [ ] Key management: ESMFold2 adapter reads Biohub token from `keys/esmkey.txt` at module init. Token is passed as Bearer auth on `/fold` requests. Missing or invalid key produces a clear error at node execution time (not startup crash). SimpleFold has no remote dependency — no key needed.
