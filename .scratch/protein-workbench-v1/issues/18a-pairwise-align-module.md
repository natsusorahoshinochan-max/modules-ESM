# 18a — `structure.pairwise_align` module

**What to build:** A new DAG node that accepts two `CandidateCollection`s of `protein.structure` items and performs index-matched SVD alignment on each `(ref[i], mobile[i])` pair. Outputs a `CandidateCollection` of `StructureAlignment` items, reusing the reference candidate IDs so downstream scorers correctly set subjects. Replaces the imperative for-loop in step 2 of `scripts/3gb1_pipeline.py` with a single composable node.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Module directory `modules/structure_pairwise_align/` with `definition.yaml`, `module.py`, `__init__.py`, and `register()` function
- [ ] Two input ports (`reference_candidates`, `mobile_candidates`), one output port (`alignments`)
- [ ] Enforces equal-length collections; raises `ValueError` on mismatch
- [ ] Reuses SVD logic from `structure.align` (Bio.SVDSuperimposer inline, no new dependency)
- [ ] Each output `Candidate` inherits `candidate_id` from the reference candidate
- [ ] Registered in `core/server.py` lifespan (import + `register_module_factory`)
- [ ] Unit tests: equal-length → correct count; identical structures → RMSD ~0; mismatched lengths → ValueError; empty collections → ValueError; candidate_id preservation; PDBs with no common residues → alignment with 0 coverage
- [ ] Hardcoded module count assertions in `test_esm3.py` and `test_proteinmpnn.py` bumped from 43 → 44
