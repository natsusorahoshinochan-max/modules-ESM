"""3GB1 four-step design pipeline (ticket 17).

Orchestrates: ESM-3 conditional generation → ESMFold2 folding +
weighted TM-score ranking → ProteinMPNN 50% redesign → final ESMFold2.

Run with: python scripts/3gb1_pipeline.py [--output-dir /path/to/output]
Requires valid API keys in keys/esmkey.txt for ESM-3 and ESMFold2.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinMPNNConstraints,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ResidueTrack,
    ScoreCollection,
)

# ── Fixed seeds for reproducibility ──────────────────────────────────

SEED_MASK_SEQ = 100
SEED_INSERT = 101
SEED_MASK_STRUCT = 102
SEED_ESM3 = 200
SEED_FIXED_MPNN_BASE = 300  # + top index


# ── Step 1: Build ESM-3 prompt & generate ────────────────────────────

def build_3gb1_prompt(pdb_path: str | Path) -> ProteinPrompt:
    """Build a conditioned ProteinPrompt from 3GB1 PDB:
    - Sequence: 20 random masks + 15 random inserted masked positions
    - Structure: 10 random masks, then extended to match new layout
    - SS: [1,19]=E, [23,30]=H, [35,56]=E, rest empty
    """
    raw_pdb = Path(pdb_path).read_text()
    ref_struct = ProteinStructure(pdb_string=raw_pdb)

    # Build residue layout (56 residues, chain A)
    layout = ResidueLayout(chain_id="A", length=56)

    # Apply residue edits to extract tracks from template
    from modules.apply_residue_edits.module import ApplyResidueEditsModule
    edits_mod = ApplyResidueEditsModule()
    ctx = RunContext(str(_project_root), "build_prompt", seed=42)
    edits_result = edits_mod.run(
        {"template_structure": ref_struct, "target_layout": layout},
        {"edits": "[]"},
        ctx,
    )
    seq_track = edits_result["sequence_track"]
    struct_track = edits_result["structure_track"]

    # Random mask 20 sequence positions
    from modules.prompt_random_mask.module import RandomMaskModule
    mask_mod = RandomMaskModule()
    ctx_seq_mask = RunContext(str(_project_root), "mask_seq", seed=SEED_MASK_SEQ)
    masked_seq = mask_mod.run({"track": seq_track}, {"count": 20}, ctx_seq_mask)["track"]

    # Random mask 10 structure positions (on the original 56-length track)
    ctx_struct_mask = RunContext(str(_project_root), "mask_struct", seed=SEED_MASK_STRUCT)
    masked_struct_56 = mask_mod.run(
        {"track": struct_track}, {"count": 10}, ctx_struct_mask
    )["track"]

    # Random insert 15 masked positions into BOTH sequence and structure tracks
    from modules.prompt_random_insert_masked.module import RandomInsertMaskedModule
    insert_mod = RandomInsertMaskedModule()

    # Sequence insert (uses SEED_INSERT)
    ctx_insert = RunContext(str(_project_root), "insert_seq", seed=SEED_INSERT)
    insert_seq_result = insert_mod.run(
        {"track": masked_seq, "layout": layout},
        {"count": 15},
        ctx_insert,
    )
    seq_track_final = insert_seq_result["track"]
    layout_final = insert_seq_result["layout"]

    # Structure insert with SAME seed so insert positions match sequence
    ctx_insert_struct = RunContext(str(_project_root), "insert_struct", seed=SEED_INSERT)
    insert_struct_result = insert_mod.run(
        {"track": masked_struct_56, "layout": layout},
        {"count": 15},
        ctx_insert_struct,
    )
    struct_track_final = insert_struct_result["track"]

    # Build SS track: [1,19]=E, [23,30]=H, [35,56]=E, rest empty
    ss_length = layout_final.length
    ss_values = [None] * ss_length
    for i in range(0, 19):
        if i < ss_length:
            ss_values[i] = "E"
    for i in range(22, 30):
        if i < ss_length:
            ss_values[i] = "H"
    for i in range(34, 56):
        if i < ss_length:
            ss_values[i] = "E"
    ss_track = ResidueTrack(values=ss_values, sentinel=None)

    # Assemble ProteinPrompt
    from modules.assemble_protein_prompt.module import AssembleProteinPromptModule
    assemble_mod = AssembleProteinPromptModule()
    ctx_assemble = RunContext(str(_project_root), "assemble", seed=42)
    prompt_result = assemble_mod.run(
        {
            "layout": layout_final,
            "sequence_track": seq_track_final,
            "structure_track": struct_track_final,
            "secondary_structure_track": ss_track,
        },
        {},
        ctx_assemble,
    )
    return prompt_result["protein_prompt"]


def step1_generate(prompt: ProteinPrompt, num_samples: int = 10) -> dict[str, Any]:
    """Run ESM-3 unified generate on the conditioned prompt."""
    from modules.esm3_generate.module import ESM3GenerateModule
    gen_mod = ESM3GenerateModule()
    ctx = RunContext(str(_project_root), "esm3_gen", seed=SEED_ESM3)
    return gen_mod.run(
        {"protein_prompt": prompt},
        {"num_samples": num_samples, "model_name": "esm3-medium-2024-08"},
        ctx,
    )


# ── Step 2: ESMFold2 folding + weighted TM-score ranking ─────────────

def step2_fold_and_rank(
    seq_candidates: CandidateCollection,
    ref_3gb1: ProteinStructure,
    esm3_struct_candidates: CandidateCollection,
    *,
    fold_module: WorkflowModule | None = None,
) -> tuple[CandidateCollection, CandidateCollection]:
    """Fold 10 sequences with ESMFold2, compute dual TM-scores, rank top 3."""
    from modules.esmfold2_fold.module import ESMFold2FoldModule
    from modules.structure_batch_tm_score.module import BatchTMScoreModule
    from modules.structure_pairwise_align.module import PairwiseAlignModule
    from modules.weighted_rank.module import WeightedRankModule

    # Fold all sequences
    fold_mod = fold_module or ESMFold2FoldModule()
    ctx_fold = RunContext(str(_project_root), "esmfold2", seed=42)
    fold_result = fold_mod.run(
        {"candidates": seq_candidates},
        {"model_name": "esmfold2-fast-2026-05"},
        ctx_fold,
    )
    fold_structs = fold_result["candidates"]

    align_mod = PairwiseAlignModule()

    # TM-score vs 3GB1 through shared alignment evidence
    ctx_align_3gb1 = RunContext(
        str(_project_root),
        "align_3gb1",
        seed=42,
    )
    align_3gb1 = align_mod.run(
        {
            "reference": ref_3gb1,
            "mobile_candidates": fold_structs,
        },
        {},
        ctx_align_3gb1,
    )
    tm_mod = BatchTMScoreModule()
    ctx_tm1 = RunContext(str(_project_root), "tm_3gb1", seed=42)
    tm_3gb1_result = tm_mod.run(
        {"alignments": align_3gb1["alignments"]},
        {"score_id": "tm_vs_3gb1"},
        ctx_tm1,
    )

    # TM-score vs index-paired ESM-3 structures through shared evidence
    ctx_align_esm3 = RunContext(
        str(_project_root),
        "align_esm3",
        seed=42,
    )
    align_esm3 = align_mod.run(
        {
            "reference_candidates": fold_structs,
            "mobile_candidates": esm3_struct_candidates,
        },
        {},
        ctx_align_esm3,
    )
    ctx_tm2 = RunContext(str(_project_root), "tm_esm3", seed=42)
    tm_esm3_result = tm_mod.run(
        {"alignments": align_esm3["alignments"]},
        {"score_id": "tm_vs_esm3"},
        ctx_tm2,
    )

    merged_scores = ScoreCollection(
        collection_id="merged-tm",
        entries=(
            tm_3gb1_result["scores"].entries
            + tm_esm3_result["scores"].entries
        ),
    )

    # Weighted rank: 0.7 * tm_vs_3gb1 + 0.3 * tm_vs_esm3
    rank_mod = WeightedRankModule()
    ctx_rank = RunContext(str(_project_root), "rank", seed=42)
    rank_result = rank_mod.run(
        {"candidates": fold_structs, "scores": merged_scores},
        {"metrics": json.dumps([
            {"score": "tm_vs_3gb1", "weight": 0.7},
            {"score": "tm_vs_esm3", "weight": 0.3},
        ])},
        ctx_rank,
    )

    # Take top 3
    from modules.top_k.module import TopKModule
    topk_mod = TopKModule()
    ctx_topk = RunContext(str(_project_root), "topk", seed=42)
    topk_result = topk_mod.run(
        {"candidates": rank_result["candidates"]},
        {"k": 3},
        ctx_topk,
    )

    return topk_result["candidates"], rank_result["scores"]


# ── Step 3: ProteinMPNN 50% redesign ─────────────────────────────────

def step3_proteinmpnn_design(
    top_structures: CandidateCollection,
) -> CandidateCollection:
    """For each of the top 3 ESMFold structures, fix 50% positions,
    generate 5 ProteinMPNN sequences (total 15)."""
    from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
    from modules.prompt_random_fixed_positions.module import (
        RandomFixedPositionsModule,
    )

    design_mod = ProteinMPNNDesignModule()
    fixed_mod = RandomFixedPositionsModule()
    all_seq_candidates: list[Candidate] = []

    for idx, struct_cand in enumerate(top_structures.items):
        struct = struct_cand.data
        if not isinstance(struct, ProteinStructure):
            continue

        # Determine sequence length from PDB CA atoms
        ca_count = sum(
            1 for line in struct.pdb_string.splitlines()
            if line.startswith("ATOM") and line[12:16].strip() == "CA"
        )

        # Generate fixed positions: 50% random
        ctx_fixed = RunContext(
            str(_project_root), f"fixed_{idx}", seed=SEED_FIXED_MPNN_BASE + idx
        )
        fixed_result = fixed_mod.run(
            {}, {"length": ca_count, "fraction": 0.5}, ctx_fixed
        )
        constraints: ProteinMPNNConstraints = fixed_result["constraints"]

        # Design with ProteinMPNN (5 sequences per structure)
        ctx_design = RunContext(str(_project_root), f"mpnn_{idx}", seed=42 + idx)
        design_result = design_mod.run(
            {"structure": struct, "constraints": constraints},
            {"num_sequences": 5},
            ctx_design,
        )
        all_seq_candidates.extend(design_result["candidates"].items)

    return CandidateCollection(
        collection_id="mpnn-all",
        item_type="protein.sequence",
        items=all_seq_candidates,
    )


# ── Step 4: Final ESMFold2 folding ───────────────────────────────────

def step4_final_fold(
    sequences: CandidateCollection,
    output_dir: str | Path,
    *,
    fold_module: WorkflowModule | None = None,
) -> CandidateCollection:
    """Fold all 15 sequences with ESMFold2 and write PDB files."""
    from modules.esmfold2_fold.module import ESMFold2FoldModule

    fold_mod = fold_module or ESMFold2FoldModule()
    ctx_fold = RunContext(str(_project_root), "final_fold", seed=42)
    fold_result = fold_mod.run(
        {"candidates": sequences},
        {"model_name": "esmfold2-fast-2026-05"},
        ctx_fold,
    )

    # Write PDB files
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for i, cand in enumerate(fold_result["candidates"].items):
        pdb_path = out / f"final_{i:03d}_{cand.candidate_id}.pdb"
        pdb_path.write_text(cand.data.pdb_string)

    return fold_result["candidates"]


# ── Main ─────────────────────────────────────────────────────────────

def run_pipeline(output_dir: str | Path = "output/3gb1_pipeline") -> dict[str, Any]:
    """Execute the complete 4-step 3GB1 design pipeline."""
    pdb_path = _project_root / "pdbs" / "3GB1.pdb"
    ref_3gb1 = ProteinStructure(pdb_string=pdb_path.read_text())

    print("=== Step 1: Building conditioned prompt & ESM-3 generation ===")
    prompt = build_3gb1_prompt(pdb_path)
    print(f"  Prompt: {prompt.num_residues} residues")
    gen_result = step1_generate(prompt, num_samples=10)
    seq_cands = gen_result["sequence_candidates"]
    struct_cands = gen_result["structure_candidates"]
    print(f"  Generated {len(seq_cands)} sequence/structure pairs")

    print("=== Step 2: ESMFold2 folding + weighted TM-score ranking ===")
    top3, rank_scores = step2_fold_and_rank(seq_cands, ref_3gb1, struct_cands)
    print(f"  Top 3 candidates selected")
    for entry in rank_scores.entries:
        if entry.score_id == "weighted_rank":
            print(f"    {entry.subjects[0]}: score={entry.value:.4f}")

    print("=== Step 3: ProteinMPNN 50% redesign ===")
    mpnn_seqs = step3_proteinmpnn_design(top3)
    print(f"  Generated {len(mpnn_seqs)} sequences")

    print("=== Step 4: Final ESMFold2 folding ===")
    final_structs = step4_final_fold(mpnn_seqs, output_dir)
    print(f"  Folded {len(final_structs)} structures → {output_dir}")

    return {
        "step1_prompt": prompt,
        "step1_sequence_candidates": seq_cands,
        "step1_structure_candidates": struct_cands,
        "step2_top3": top3,
        "step3_sequences": mpnn_seqs,
        "step4_structures": final_structs,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="3GB1 design pipeline")
    parser.add_argument(
        "--output-dir",
        default="output/3gb1_pipeline",
        help="Output directory for final PDB files",
    )
    args = parser.parse_args()
    run_pipeline(args.output_dir)
