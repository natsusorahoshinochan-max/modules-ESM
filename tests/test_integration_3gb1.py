"""Integration test for 3GB1 four-step pipeline (ticket 17).

Mocks all external API calls (ESM-3, ESMFold2, ProteinMPNN) and
verifies the full pipeline wiring, counts, and output correctness.
"""

import importlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import torch

from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinMPNNConstraints,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)

# Import pipeline module (filename starts with digit, use importlib)
_pipeline = importlib.import_module("scripts.3gb1_pipeline")
build_3gb1_prompt = _pipeline.build_3gb1_prompt
step1_generate = _pipeline.step1_generate
step2_fold_and_rank = _pipeline.step2_fold_and_rank
step3_proteinmpnn_design = _pipeline.step3_proteinmpnn_design
step4_final_fold = _pipeline.step4_final_fold


# ── Helpers ───────────────────────────────────────────────────────────

AA3 = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "K": "LYS",
    "L": "LEU",
    "M": "MET",
    "N": "ASN",
    "P": "PRO",
    "Q": "GLN",
    "R": "ARG",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
    "Y": "TYR",
    "_": "ALA",
}


def _pdb_line(
    serial: int,
    atom: str,
    res: str,
    chain: str,
    resnum: int,
    x: float,
    y: float,
    z: float,
) -> str:
    """Build a valid PDB ATOM line with correct column positions."""
    aa3 = AA3.get(res, "ALA")
    return (
        f"ATOM  {serial:5d}  {atom:<3s} {aa3} {chain}{resnum:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           {atom[0]:>1s}"
    )


def _make_mock_pdb(sequence: str, seed: int = 0) -> str:
    """Build a valid PDB string with N,CA,C,O atoms per residue."""
    lines = ["HEADER    MOCK"]
    serial = 1
    for i, res in enumerate(sequence):
        resnum = i + 1
        x = i * 3.8 + seed * 0.001
        y = 0.0
        z = 0.0
        lines.append(_pdb_line(serial, "N", res, "A", resnum, x, y, z))
        serial += 1
        lines.append(_pdb_line(serial, "CA", res, "A", resnum, x, y, z))
        serial += 1
        lines.append(_pdb_line(serial, "C", res, "A", resnum, x, y, z))
        serial += 1
        lines.append(_pdb_line(serial, "O", res, "A", resnum, x, y, z))
        serial += 1
    lines.append("END")
    return "\n".join(lines)


def _make_mock_esm_protein(sequence: str, seed: int = 0) -> MagicMock:
    """Create a mock ESMProtein with sequence, PDB, and scores."""
    n = len(sequence)
    mock = MagicMock()
    mock.sequence = sequence
    mock.coordinates = torch.zeros((n, 37, 3))
    mock.ptm = torch.tensor([0.85 + seed * 0.01])
    mock.plddt = torch.tensor([0.9 - seed * 0.005] * n)
    mock.pae = None
    mock.to_pdb_string.return_value = _make_mock_pdb(sequence, seed)
    return mock


def _make_mock_fold_result(
    pdb_string: str, ptm: float = 0.9, plddt_vals: list[float] | None = None
) -> tuple[ProteinStructure, ScoreCollection]:
    struct = ProteinStructure(pdb_string=pdb_string)
    if plddt_vals is None:
        ca_count = sum(
            1
            for line in pdb_string.splitlines()
            if line.startswith("ATOM") and line[12:16].strip() == "CA"
        )
        plddt_vals = [0.8] * ca_count
    entries = [
        Score(score_id="ptm", value=ptm, subjects=["folded"]),
        Score(
            score_id="plddt",
            value=sum(plddt_vals) / len(plddt_vals),
            subjects=["folded"],
            details={"per_residue": plddt_vals},
        ),
    ]
    return struct, ScoreCollection(collection_id="mock", entries=entries)


def _ca_count(pdb_string: str) -> int:
    return sum(
        1
        for line in pdb_string.splitlines()
        if line.startswith("ATOM") and line[12:16].strip() == "CA"
    )


# ── Integration Tests ─────────────────────────────────────────────────


class Test3GB1Pipeline:
    def test_full_pipeline_mocked(self) -> None:
        """Run the complete pipeline with mocked external calls."""
        pdb_path = Path(__file__).parent.parent / "pdbs" / "3GB1.pdb"
        ref_3gb1 = ProteinStructure(pdb_string=pdb_path.read_text())

        # ── Step 1: Build prompt ──
        prompt = build_3gb1_prompt(pdb_path)

        assert isinstance(prompt, ProteinPrompt)
        assert prompt.num_residues == 71
        seq_track = prompt.sequence_track
        assert seq_track is not None
        assert seq_track.specified_count() == 36
        assert prompt.secondary_structure_track is not None
        # Structure track should also be 71 long
        assert prompt.structure_track is not None
        assert len(prompt.structure_track) == 71

        # ── Mock ESM-3 generate ──
        num_samples = 10
        mock_eps = [
            response
            for i in range(num_samples)
            for response in (
                _make_mock_esm_protein("A" * 56 + "G" * 15, seed=i),
                _make_mock_esm_protein("A" * 56 + "G" * 15, seed=i),
            )
        ]

        mock_esm3_client = MagicMock()
        mock_esm3_client.generate.side_effect = mock_eps

        with patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=mock_esm3_client,
        ):
            gen_result = step1_generate(prompt, num_samples=num_samples)

        seq_cands = gen_result["sequence_candidates"]
        struct_cands = gen_result["structure_candidates"]
        assert len(seq_cands) == num_samples
        assert len(struct_cands) == num_samples

        # ── Mock ESMFold2 fold ──
        fold_pdb_56 = _make_mock_pdb("A" * 56)

        def mock_fold_sequence(sequence, **kwargs):
            return _make_mock_fold_result(fold_pdb_56, ptm=0.9, plddt_vals=[0.8] * 56)

        with patch(
            "modules.esmfold2_adapter.fold_sequence",
            side_effect=mock_fold_sequence,
        ):
            top3, rank_scores = step2_fold_and_rank(seq_cands, ref_3gb1, struct_cands)

        assert len(top3) == 3
        weighted_entries = [
            e for e in rank_scores.entries if e.score_id == "weighted_rank"
        ]
        assert len(weighted_entries) == 10

        # ── Mock ProteinMPNN design ──
        def mock_design_sequences(
            pdb_string, model_name, num_sequences, temperature, constraints=None
        ):
            n = _ca_count(pdb_string)
            import random

            rng = random.Random(42)
            aas = "ACDEFGHIKLMNPQRSTVWY"
            sequences = [
                ProteinSequence(sequence="".join(rng.choice(aas) for _ in range(n)))
                for _ in range(num_sequences)
            ]
            return sequences, -0.95

        with patch(
            "modules.proteinmpnn.module_design.design_sequences",
            side_effect=mock_design_sequences,
        ):
            mpnn_seqs = step3_proteinmpnn_design(top3)

        assert len(mpnn_seqs) == 15

        # ── Mock final ESMFold2 fold ──
        with tempfile.TemporaryDirectory() as tmpdir:

            def mock_final_fold(sequence, **kwargs):
                return _make_mock_fold_result(
                    fold_pdb_56, ptm=0.85, plddt_vals=[0.7] * 56
                )

            with patch(
                "modules.esmfold2_adapter.fold_sequence",
                side_effect=mock_final_fold,
            ):
                final_structs = step4_final_fold(mpnn_seqs, tmpdir)

            assert len(final_structs) == 15
            pdb_files = sorted(Path(tmpdir).glob("final_*.pdb"))
            assert len(pdb_files) == 15
            for pf in pdb_files:
                content = pf.read_text()
                assert "ATOM" in content

    def test_prompt_ss_track_correct(self) -> None:
        pdb_path = Path(__file__).parent.parent / "pdbs" / "3GB1.pdb"
        prompt = build_3gb1_prompt(pdb_path)
        ss = prompt.secondary_structure_track
        assert ss is not None
        for i in range(19):
            assert ss.values[i] == "E", f"Position {i} should be E"
        for i in range(22, 30):
            assert ss.values[i] == "H", f"Position {i} should be H"
        for i in range(34, 56):
            assert ss.values[i] == "E", f"Position {i} should be E"
        for i in range(19, 22):
            assert ss.values[i] is None, f"Position {i} should be None"
        for i in range(30, 34):
            assert ss.values[i] is None, f"Position {i} should be None"

    def test_step3_fixed_positions_constraints(self) -> None:
        pdb_56 = _make_mock_pdb("A" * 56)
        top3 = CandidateCollection(
            collection_id="top3",
            item_type="protein.structure",
            items=[
                Candidate(
                    candidate_id=f"top_{i}",
                    data=ProteinStructure(pdb_string=pdb_56),
                )
                for i in range(3)
            ],
        )

        captured_constraints = []

        def capture_design(
            pdb_string, model_name, num_sequences, temperature, constraints=None
        ):
            captured_constraints.append(constraints)
            n = _ca_count(pdb_string)
            import random

            rng = random.Random(42)
            aas = "ACDEFGHIKLMNPQRSTVWY"
            sequences = [
                ProteinSequence(sequence="".join(rng.choice(aas) for _ in range(n)))
                for _ in range(num_sequences)
            ]
            return sequences, -0.95

        with patch(
            "modules.proteinmpnn.module_design.design_sequences",
            side_effect=capture_design,
        ):
            result = step3_proteinmpnn_design(top3)

        assert len(result) == 15
        assert len(captured_constraints) == 3
        for c in captured_constraints:
            assert isinstance(c, ProteinMPNNConstraints)
            assert c.fixed_positions is not None
            assert len(c.fixed_positions) == 28
            assert all(0 <= p < 56 for p in c.fixed_positions)
            assert len(c.fixed_positions) == len(set(c.fixed_positions))

    def test_step4_output_count(self) -> None:
        seqs = CandidateCollection(
            collection_id="mpnn_seqs",
            item_type="protein.sequence",
            items=[
                Candidate(
                    candidate_id=f"seq_{i}",
                    data=ProteinSequence(sequence="A" * 56),
                )
                for i in range(15)
            ],
        )

        pdb_56 = _make_mock_pdb("A" * 56)

        def mock_fold(sequence, **kwargs):
            return _make_mock_fold_result(pdb_56, ptm=0.8, plddt_vals=[0.7] * 56)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "modules.esmfold2_adapter.fold_sequence",
                side_effect=mock_fold,
            ):
                result = step4_final_fold(seqs, tmpdir)

            assert len(result) == 15
            pdb_files = sorted(Path(tmpdir).glob("final_*.pdb"))
            assert len(pdb_files) == 15
