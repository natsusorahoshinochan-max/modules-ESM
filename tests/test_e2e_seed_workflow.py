"""End-to-end integration test: execute 3GB1 seed workflow DAG with mocked APIs.

Verifies that all 22 nodes in examples/3gb1_pipeline.json complete successfully
and that the complete data flow (prompt → ESM3 → Fold → TM-score → Rank →
ProteinMPNN → FinalFold) produces expected output counts.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import torch

from core.graph import Workflow, WorkflowNode, WorkflowEdge
from core.executor import Executor
from core.module_registry import ModuleRegistry, TypeRegistry, discover_modules


# ── Module instances (reused across tests) ────────────────────────────

def _build_modules():
    from modules.import_structure import ImportStructureModule
    from modules.build_residue_layout import BuildResidueLayoutModule
    from modules.apply_residue_edits import ApplyResidueEditsModule
    from modules.override_residue_track import OverrideResidueTrackModule
    from modules.assemble_protein_prompt import AssembleProteinPromptModule
    from modules.esm3_generate.module import ESM3GenerateModule
    from modules.esmfold2_fold.module import ESMFold2FoldModule
    from modules.structure_pairwise_align.module import PairwiseAlignModule
    from modules.structure_batch_tm_score.module import BatchTMScoreModule
    from modules.compute_dssp.module import ComputeDSSPModule
    from modules.merge_scores.module import MergeScoresModule
    from modules.top_k.module import TopKModule
    from modules.weighted_rank.module import WeightedRankModule
    from modules.prompt_random_mask.module import RandomMaskModule
    from modules.prompt_random_insert_masked.module import RandomInsertMaskedModule
    from modules.prompt_random_fixed_positions.module import RandomFixedPositionsModule
    from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
    from modules.selection_concat.module import ConcatCandidatesModule

    return {
        "import.structure": ImportStructureModule(),
        "prompt.build_residue_layout": BuildResidueLayoutModule(),
        "prompt.apply_residue_edits": ApplyResidueEditsModule(),
        "prompt.random_mask": RandomMaskModule(),
        "prompt.random_insert_masked": RandomInsertMaskedModule(),
        "prompt.random_fixed_positions": RandomFixedPositionsModule(),
        "prompt.override_residue_track": OverrideResidueTrackModule(),
        "prompt.assemble_protein_prompt": AssembleProteinPromptModule(),
        "esm3.generate": ESM3GenerateModule(),
        "esmfold2.fold": ESMFold2FoldModule(),
        "structure.pairwise_align": PairwiseAlignModule(),
        "structure.batch_tm_score": BatchTMScoreModule(),
        "compute.dssp": ComputeDSSPModule(),
        "scoring.merge": MergeScoresModule(),
        "selection.top_k": TopKModule(),
        "selection.weighted_rank": WeightedRankModule(),
        "selection.concat": ConcatCandidatesModule(),
        "proteinmpnn.design": ProteinMPNNDesignModule(),
    }


# ── Mock helpers ──────────────────────────────────────────────────────

AA3 = dict(zip("ACDEFGHIKLMNPQRSTVWY",
    "ALA CYS ASP GLU PHE GLY HIS ILE LYS LEU MET ASN PRO GLN ARG SER THR VAL TRP TYR".split()))
AA3["G"] = "GLY"


def _make_mock_pdb(sequence, seed=0):
    if hasattr(sequence, "sequence"):
        sequence = sequence.sequence
    lines = ["HEADER    MOCK"]
    serial = 1
    for i, res in enumerate(sequence):
        resnum = i + 1
        x = i * 3.8 + seed * 0.01
        aa3 = AA3.get(res, "ALA")
        for atom in ["N", "CA", "C", "O"]:
            lines.append(
                f"ATOM  {serial:5d}  {atom:<3s} {aa3} A{resnum:4d}    "
                f"{x:8.3f}{0:8.3f}{0:8.3f}  1.00  0.00           {atom[0]:>1s}"
            )
            serial += 1
    lines.append("END")
    return "\n".join(lines)


def _make_mock_esm_protein(sequence, seed=0):
    mock = MagicMock()
    mock.sequence = sequence
    mock.ptm = torch.tensor([0.85 + seed * 0.01])
    mock.plddt = torch.tensor([0.9] * len(sequence))
    mock.to_pdb_string.return_value = _make_mock_pdb(sequence, seed)
    return mock


def _mock_fold(sequence, **kw):
    from datatypes import ProteinStructure, Score, ScoreCollection
    seq_str = sequence.sequence if hasattr(sequence, "sequence") else sequence
    n = len(seq_str)
    struct = ProteinStructure(pdb_string=_make_mock_pdb(seq_str))
    entries = [
        Score(score_id="ptm", value=0.9, subjects=["folded"]),
        Score(
            score_id="plddt", value=0.85, subjects=["folded"],
            details={"per_residue": [0.8] * n},
        ),
    ]
    return struct, ScoreCollection(collection_id="m", entries=entries)


def _mock_design(pdb_string, model_name, num_sequences, temperature, constraints=None):
    from datatypes import ProteinSequence
    import random
    rng = random.Random(42)
    aas = "ACDEFGHIKLMNPQRSTVWY"
    n = sum(
        1 for l in pdb_string.splitlines()
        if l.startswith("ATOM") and l[12:16].strip() == "CA"
    )
    sequences = [
        ProteinSequence(sequence="".join(rng.choice(aas) for _ in range(n)))
        for _ in range(num_sequences)
    ]
    return sequences, -0.95


# ── Tests ─────────────────────────────────────────────────────────────

class TestE2ESeedWorkflow:
    """End-to-end execution of the 3GB1 seed workflow DAG."""

    def test_all_22_nodes_complete(self) -> None:
        """Every node in the seed workflow DAG completes without error."""
        wf_path = Path(__file__).parent.parent / "examples" / "3gb1_pipeline.json"
        wf_data = json.loads(wf_path.read_text())

        workflow = Workflow()
        for n in wf_data["nodes"]:
            workflow.add_node(WorkflowNode(
                node_id=n["node_id"], module_id=n["module_id"],
                module_version="1.0.0", parameters=n["parameters"],
            ))
        for e in wf_data["edges"]:
            workflow.add_edge(WorkflowEdge(**e))

        assert not workflow.validate_acyclic()
        assert len(workflow.nodes) == 22
        assert len(workflow.edges) == 31

        mods = _build_modules()
        dssp_mod = mods["compute.dssp"]

        seq_template = "MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE"
        seq_71 = seq_template + "G" * 15
        N = 10

        mock_esm3 = MagicMock()
        mock_esm3.generate.side_effect = [
            _make_mock_esm_protein(seq_71, seed=i) for i in range(N)
        ]

        from datatypes import ResidueTrack
        mock_ss = ResidueTrack(
            values=["E"] * 10 + ["H"] * 10 + ["E"] * 36, sentinel=None
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "modules.esm3_adapter.create_esm3_client",
                return_value=mock_esm3,
            ), patch(
                "modules.esmfold2_adapter.fold_sequence",
                side_effect=_mock_fold,
            ), patch(
                "modules.proteinmpnn.module_design.design_sequences",
                side_effect=_mock_design,
            ), patch.object(
                dssp_mod, "run",
                return_value={"secondary_structure_track": mock_ss},
            ):
                executor = Executor()
                result = asyncio.run(executor.execute(
                    workflow=workflow, modules=mods,
                    project_dir=tmpdir, run_id="e2e-test", seed=42,
                ))

        completed = set(result.keys())
        all_nodes = set(workflow.nodes.keys())
        assert completed == all_nodes, (
            f"Missing nodes: {all_nodes - completed}"
        )

    def test_data_flow_counts(self) -> None:
        """Verify output counts at each pipeline stage."""
        wf_path = Path(__file__).parent.parent / "examples" / "3gb1_pipeline.json"
        wf_data = json.loads(wf_path.read_text())

        workflow = Workflow()
        for n in wf_data["nodes"]:
            workflow.add_node(WorkflowNode(
                node_id=n["node_id"], module_id=n["module_id"],
                module_version="1.0.0", parameters=n["parameters"],
            ))
        for e in wf_data["edges"]:
            workflow.add_edge(WorkflowEdge(**e))

        mods = _build_modules()
        dssp_mod = mods["compute.dssp"]

        seq_template = "MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE"
        seq_71 = seq_template + "G" * 15
        N = 10

        mock_esm3 = MagicMock()
        mock_esm3.generate.side_effect = [
            _make_mock_esm_protein(seq_71, seed=i) for i in range(N)
        ]

        from datatypes import ResidueTrack
        mock_ss = ResidueTrack(
            values=["E"] * 10 + ["H"] * 10 + ["E"] * 36, sentinel=None
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "modules.esm3_adapter.create_esm3_client",
                return_value=mock_esm3,
            ), patch(
                "modules.esmfold2_adapter.fold_sequence",
                side_effect=_mock_fold,
            ), patch(
                "modules.proteinmpnn.module_design.design_sequences",
                side_effect=_mock_design,
            ), patch.object(
                dssp_mod, "run",
                return_value={"secondary_structure_track": mock_ss},
            ):
                executor = Executor()
                result = asyncio.run(executor.execute(
                    workflow=workflow, modules=mods,
                    project_dir=tmpdir, run_id="e2e-counts", seed=42,
                ))

        # Step 1: ESM-3 generation
        assert len(result["esm3_gen"]["sequence_candidates"]) == N
        assert len(result["esm3_gen"]["structure_candidates"]) == N

        # Step 2: Folding
        assert len(result["fold_seq"]["candidates"]) == N

        # Step 2: Pairwise alignment
        assert len(result["align_pw"]["alignments"]) == N

        # Step 2: TM-score vs 3GB1
        assert result["tm_3gb1"]["scores"].entries[0].score_id == "tm_vs_3gb1"
        assert len(result["tm_3gb1"]["scores"].entries) == N

        # Step 2: TM-score vs ESM-3 (via alignments)
        assert result["tm_esm3"]["scores"].entries[0].score_id == "tm_vs_esm3"
        assert len(result["tm_esm3"]["scores"].entries) == N

        # Step 2: Merged scores (N from each source)
        assert len(result["merge_tm"]["scores"].entries) == 2 * N

        # Step 2: Top-K selection
        assert len(result["top3"]["candidates"]) == 3

        # Step 3: ProteinMPNN design
        assert len(result["mpnn_0"]["candidates"]) == 15

        # Step 4: Final folding
        assert len(result["final_fold"]["candidates"]) == 15

    def test_workflow_json_port_names_valid(self) -> None:
        """All edge port names match their module definitions."""
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)

        wf_path = Path(__file__).parent.parent / "examples" / "3gb1_pipeline.json"
        wf_data = json.loads(wf_path.read_text())

        nodes_by_id = {n["node_id"]: n for n in wf_data["nodes"]}

        for edge in wf_data["edges"]:
            src_node = nodes_by_id[edge["source_node_id"]]
            tgt_node = nodes_by_id[edge["target_node_id"]]

            src_mod = mr.get(src_node["module_id"])
            tgt_mod = mr.get(tgt_node["module_id"])

            assert src_mod is not None, f"Unknown module: {src_node['module_id']}"
            assert tgt_mod is not None, f"Unknown module: {tgt_node['module_id']}"

            src_ports = {p.name for p in src_mod.output_ports}
            tgt_ports = {p.name for p in tgt_mod.input_ports}

            assert edge["source_port"] in src_ports, (
                f"Edge {edge['source_node_id']}.{edge['source_port']}: "
                f"port not in {src_mod.module_id} outputs {src_ports}"
            )
            assert edge["target_port"] in tgt_ports, (
                f"Edge {edge['target_node_id']}.{edge['target_port']}: "
                f"port not in {tgt_mod.module_id} inputs {tgt_ports}"
            )
