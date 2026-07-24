"""Tests for scoring, alignment, metrics, and DSSP modules (ticket 09)."""

import uuid
from unittest.mock import patch

import numpy as np
import pytest

from core.run_context import RunContext
from datatypes import (
    ProteinStructure,
    ResidueTrack,
    Score,
    ScoreCollection,
    StructureAlignment,
)

# ── Shared test data ─────────────────────────────────────────────────

SAMPLE_PDB_3RES = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA A   1       2.009   1.421   0.000  1.00  0.00           C
ATOM      4  O   ALA A   1       1.223   2.371   0.000  1.00  0.00           O
ATOM      5  N   GLY A   2       3.309   1.681   0.000  1.00  0.00           N
ATOM      6  CA  GLY A   2       3.909   3.009   0.000  1.00  0.00           C
ATOM      7  C   GLY A   2       3.309   4.309   0.000  1.00  0.00           C
ATOM      8  O   GLY A   2       2.109   4.409   0.000  1.00  0.00           O
ATOM      9  N   SER A   3       4.109   5.309   0.000  1.00  0.00           N
ATOM     10  CA  SER A   3       3.609   6.609   0.000  1.00  0.00           C
ATOM     11  C   SER A   3       2.509   7.109   0.000  1.00  0.00           C
ATOM     12  O   SER A   3       1.509   6.409   0.000  1.00  0.00           O
END
"""

SAMPLE_PDB_SHIFTED = """\
ATOM      1  N   ALA A   1       0.100   0.100   0.100  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.558   0.100   0.100  1.00  0.00           C
ATOM      3  C   ALA A   1       2.109   1.521   0.100  1.00  0.00           C
ATOM      4  O   ALA A   1       1.323   2.471   0.100  1.00  0.00           O
ATOM      5  N   GLY A   2       3.409   1.781   0.100  1.00  0.00           N
ATOM      6  CA  GLY A   2       4.009   3.109   0.100  1.00  0.00           C
ATOM      7  C   GLY A   2       3.409   4.409   0.100  1.00  0.00           C
ATOM      8  O   GLY A   2       2.209   4.509   0.100  1.00  0.00           O
ATOM      9  N   SER A   3       4.209   5.409   0.100  1.00  0.00           N
ATOM     10  CA  SER A   3       3.709   6.709   0.100  1.00  0.00           C
ATOM     11  C   SER A   3       2.609   7.209   0.100  1.00  0.00           C
ATOM     12  O   SER A   3       1.609   6.509   0.100  1.00  0.00           O
END
"""


def _make_alignment(rmsd: float = 0.5) -> StructureAlignment:
    """Create a test StructureAlignment."""
    return StructureAlignment(
        residue_map=[("A:1", "A:1"), ("A:2", "A:2"), ("A:3", "A:3")],
        chain_map={"A": "A"},
        rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        translation=[0.0, 0.0, 0.0],
        rmsd=rmsd,
        coverage=1.0,
    )


# ── Structure Alignment Module ───────────────────────────────────────

class TestStructureAlign:
    def test_aligns_identical_structures(self) -> None:
        from modules.structure_align.module import StructureAlignModule
        mod = StructureAlignModule()
        ctx = RunContext("/tmp/test", "n1")
        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        mob = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)

        result = mod.run({"reference": ref, "mobile": mob}, {}, ctx)
        alignment = result["alignment"]

        assert isinstance(alignment, StructureAlignment)
        assert alignment.rmsd == pytest.approx(0.0, abs=0.01)
        assert alignment.coverage == pytest.approx(1.0)
        assert len(alignment.residue_map) == 3
        assert alignment.chain_map == {"A": "A"}

    def test_aligns_shifted_structures(self) -> None:
        from modules.structure_align.module import StructureAlignModule
        mod = StructureAlignModule()
        ctx = RunContext("/tmp/test", "n1")
        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        mob = ProteinStructure(pdb_string=SAMPLE_PDB_SHIFTED)

        result = mod.run({"reference": ref, "mobile": mob}, {}, ctx)
        alignment = result["alignment"]

        assert alignment.rmsd > 0.0
        assert alignment.coverage == pytest.approx(1.0)
        assert len(alignment.residue_map) == 3

    def test_missing_reference_raises(self) -> None:
        from modules.structure_align.module import StructureAlignModule
        mod = StructureAlignModule()
        ctx = RunContext("/tmp/test", "n1")
        mob = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        with pytest.raises(ValueError, match="reference"):
            mod.run({"mobile": mob}, {}, ctx)

    def test_missing_mobile_raises(self) -> None:
        from modules.structure_align.module import StructureAlignModule
        mod = StructureAlignModule()
        ctx = RunContext("/tmp/test", "n1")
        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        with pytest.raises(ValueError, match="mobile"):
            mod.run({"reference": ref}, {}, ctx)

    def test_empty_pdb_raises(self) -> None:
        from modules.structure_align.module import StructureAlignModule
        mod = StructureAlignModule()
        ctx = RunContext("/tmp/test", "n1")
        empty = ProteinStructure(pdb_string="HEADER EMPTY\nEND\n")
        with pytest.raises(ValueError, match="No CA atoms"):
            mod.run({"reference": empty, "mobile": empty}, {}, ctx)


# ── TM-score Module ──────────────────────────────────────────────────

class TestTMScore:
    def test_identical_structures_tm_1(self) -> None:
        from modules.structure_tm_score.module import StructureTMScoreModule
        mod = StructureTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")
        alignment = _make_alignment(rmsd=0.0)

        result = mod.run({"alignment": alignment}, {}, ctx)
        scores = result["scores"]

        assert isinstance(scores, ScoreCollection)
        tm_entry = [s for s in scores.entries if s.score_id == "tm_score"]
        assert len(tm_entry) == 1
        assert tm_entry[0].value == pytest.approx(1.0, abs=0.01)

    def test_divergent_structures_tm_low(self) -> None:
        from modules.structure_tm_score.module import StructureTMScoreModule
        mod = StructureTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")
        alignment = _make_alignment(rmsd=10.0)

        result = mod.run({"alignment": alignment}, {}, ctx)
        scores = result["scores"]
        tm_entry = [s for s in scores.entries if s.score_id == "tm_score"]
        assert tm_entry[0].value < 0.5

    def test_missing_alignment_raises(self) -> None:
        from modules.structure_tm_score.module import StructureTMScoreModule
        mod = StructureTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="alignment"):
            mod.run({}, {}, ctx)


# ── RMSD Module ──────────────────────────────────────────────────────

class TestRMSD:
    def test_reads_rmsd_from_alignment(self) -> None:
        from modules.structure_rmsd.module import StructureRMSDModule
        mod = StructureRMSDModule()
        ctx = RunContext("/tmp/test", "n1")
        alignment = _make_alignment(rmsd=2.345)

        result = mod.run({"alignment": alignment}, {}, ctx)
        scores = result["scores"]

        rmsd_entry = [s for s in scores.entries if s.score_id == "rmsd"]
        assert len(rmsd_entry) == 1
        assert rmsd_entry[0].value == pytest.approx(2.345, abs=0.001)
        assert rmsd_entry[0].details["unit"] == "angstroms"
        assert rmsd_entry[0].details["aligned_residues"] == 3

    def test_missing_alignment_raises(self) -> None:
        from modules.structure_rmsd.module import StructureRMSDModule
        mod = StructureRMSDModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="alignment"):
            mod.run({}, {}, ctx)


# ── DSSP Module ──────────────────────────────────────────────────────

class TestDSSPModule:
    def test_runs_mkdssp_and_returns_track(self) -> None:
        from modules.compute_dssp.module import ComputeDSSPModule
        mod = ComputeDSSPModule()
        ctx = RunContext("/tmp/test", "n1")
        struct = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)

        result = mod.run({"structure": struct}, {}, ctx)
        track = result["secondary_structure_track"]

        assert isinstance(track, ResidueTrack)
        assert len(track) == 3  # 3 residues
        # All codes should be valid DSSP codes
        for v in track.values:
            assert v in {"H", "B", "E", "G", "I", "T", "S", "-"}

    def test_missing_structure_raises(self) -> None:
        from modules.compute_dssp.module import ComputeDSSPModule
        mod = ComputeDSSPModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="structure"):
            mod.run({}, {}, ctx)


# ── Secondary Structure Agreement Module ─────────────────────────────

class TestSSAgreement:
    def test_identical_tracks_full_overlap(self) -> None:
        from modules.secondary_structure_agreement.module import (
            SecondaryStructureAgreementModule,
        )
        mod = SecondaryStructureAgreementModule()
        ctx = RunContext("/tmp/test", "n1")
        expected = ResidueTrack(values=["H", "E", "-"], sentinel=None)
        observed = ResidueTrack(values=["H", "E", "-"], sentinel=None)

        result = mod.run({"expected": expected, "observed": observed}, {}, ctx)
        scores = result["scores"]

        ss_entry = [s for s in scores.entries if s.score_id == "ss_overlap"]
        assert len(ss_entry) == 1
        assert ss_entry[0].value == pytest.approx(1.0)

    def test_coarse_class_matches(self) -> None:
        from modules.secondary_structure_agreement.module import (
            SecondaryStructureAgreementModule,
        )
        mod = SecondaryStructureAgreementModule()
        ctx = RunContext("/tmp/test", "n1")
        # H and G are both helix; B and E are both sheet; - and T are both coil
        expected = ResidueTrack(values=["H", "B", "-"], sentinel=None)
        observed = ResidueTrack(values=["G", "E", "T"], sentinel=None)

        result = mod.run(
            {"expected": expected, "observed": observed},
            {"coarse": True},
            ctx,
        )
        scores = result["scores"]
        ss_entry = [s for s in scores.entries if s.score_id == "ss_overlap"]
        assert ss_entry[0].value == pytest.approx(1.0)

    def test_mismatched_tracks(self) -> None:
        from modules.secondary_structure_agreement.module import (
            SecondaryStructureAgreementModule,
        )
        mod = SecondaryStructureAgreementModule()
        ctx = RunContext("/tmp/test", "n1")
        expected = ResidueTrack(values=["H", "E", "-"], sentinel=None)
        observed = ResidueTrack(values=["E", "H", "H"], sentinel=None)

        result = mod.run({"expected": expected, "observed": observed}, {}, ctx)
        scores = result["scores"]
        ss_entry = [s for s in scores.entries if s.score_id == "ss_overlap"]
        assert ss_entry[0].value == pytest.approx(0.0)

    def test_missing_inputs_raises(self) -> None:
        from modules.secondary_structure_agreement.module import (
            SecondaryStructureAgreementModule,
        )
        mod = SecondaryStructureAgreementModule()
        ctx = RunContext("/tmp/test", "n1")
        track = ResidueTrack(values=["H"], sentinel=None)
        with pytest.raises(ValueError, match="expected"):
            mod.run({"observed": track}, {}, ctx)
        with pytest.raises(ValueError, match="observed"):
            mod.run({"expected": track}, {}, ctx)


# ── Aggregate Confidence Module ──────────────────────────────────────

class TestAggregateConfidence:
    def test_computes_summary_statistics(self) -> None:
        from modules.aggregate_confidence.module import AggregateConfidenceModule
        mod = AggregateConfidenceModule()
        ctx = RunContext("/tmp/test", "n1")
        scores = ScoreCollection(
            collection_id="test",
            entries=[
                Score(score_id="plddt", value=0.8, subjects=[],
                      details={"per_residue": [0.9, 0.8, 0.7]}),
                Score(score_id="plddt", value=0.6, subjects=[],
                      details={"per_residue": [0.6, 0.5, 0.7]}),
            ],
        )

        result = mod.run({"scores": scores}, {}, ctx)
        out_scores = result["scores"]

        ids = {s.score_id for s in out_scores.entries}
        assert "confidence_mean" in ids
        assert "confidence_median" in ids
        assert "confidence_min" in ids
        assert "confidence_max" in ids

        mean_entry = [s for s in out_scores.entries if s.score_id == "confidence_mean"]
        assert mean_entry[0].value == pytest.approx(0.7)

    def test_missing_input_raises(self) -> None:
        from modules.aggregate_confidence.module import AggregateConfidenceModule
        mod = AggregateConfidenceModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="scores"):
            mod.run({}, {}, ctx)


# ── Merge Scores Module ──────────────────────────────────────────────

class TestMergeScores:
    def test_merges_two_collections(self) -> None:
        from modules.merge_scores.module import MergeScoresModule
        mod = MergeScoresModule()
        ctx = RunContext("/tmp/test", "n1")
        sc_a = ScoreCollection(
            collection_id="a",
            entries=[Score(score_id="plddt", value=0.8, subjects=[])],
        )
        sc_b = ScoreCollection(
            collection_id="b",
            entries=[Score(score_id="tm_score", value=0.95, subjects=[])],
        )

        result = mod.run({"scores_a": sc_a, "scores_b": sc_b}, {}, ctx)
        merged = result["scores"]

        assert len(merged.entries) == 2
        assert {s.score_id for s in merged.entries} == {"plddt", "tm_score"}

    def test_merges_three_collections(self) -> None:
        from modules.merge_scores.module import MergeScoresModule
        mod = MergeScoresModule()
        ctx = RunContext("/tmp/test", "n1")
        sc_a = ScoreCollection("a", [Score(score_id="a", value=1.0, subjects=[])])
        sc_b = ScoreCollection("b", [Score(score_id="b", value=2.0, subjects=[])])
        sc_c = ScoreCollection("c", [Score(score_id="c", value=3.0, subjects=[])])

        result = mod.run(
            {"scores_a": sc_a, "scores_b": sc_b, "scores_c": sc_c}, {}, ctx
        )
        assert len(result["scores"].entries) == 3

    def test_no_inputs_raises(self) -> None:
        from modules.merge_scores.module import MergeScoresModule
        mod = MergeScoresModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="At least one"):
            mod.run({}, {}, ctx)
