"""Tests for structure.batch_tm_score module (ticket 16)."""

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinStructure,
    ScoreCollection,
)

# 3-residue PDB fixtures
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

# Genuinely perturbed: coordinates scaled by 2x, so shape is different
SAMPLE_PDB_SCALED = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       2.916   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA A   1       4.018   2.842   0.000  1.00  0.00           C
ATOM      4  O   ALA A   1       2.446   4.742   0.000  1.00  0.00           O
ATOM      5  N   GLY A   2       6.618   3.362   0.000  1.00  0.00           N
ATOM      6  CA  GLY A   2       7.818   6.018   0.000  1.00  0.00           C
ATOM      7  C   GLY A   2       6.618   8.618   0.000  1.00  0.00           C
ATOM      8  O   GLY A   2       4.218   8.818   0.000  1.00  0.00           O
ATOM      9  N   SER A   3       8.218  10.618   0.000  1.00  0.00           N
ATOM     10  CA  SER A   3       7.218  13.218   0.000  1.00  0.00           C
ATOM     11  C   SER A   3       5.018  14.218   0.000  1.00  0.00           C
ATOM     12  O   SER A   3       3.018  12.818   0.000  1.00  0.00           O
END
"""

DIFFERENT_CHAIN_PDB = """\
ATOM      1  N   ALA B   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA B   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA B   1       2.009   1.421   0.000  1.00  0.00           C
ATOM      4  O   ALA B   1       1.223   2.371   0.000  1.00  0.00           O
ATOM      5  N   GLY B   2       3.309   1.681   0.000  1.00  0.00           N
ATOM      6  CA  GLY B   2       3.909   3.009   0.000  1.00  0.00           C
ATOM      7  C   GLY B   2       3.309   4.309   0.000  1.00  0.00           C
ATOM      8  O   GLY B   2       2.109   4.409   0.000  1.00  0.00           O
ATOM      9  N   SER B   3       4.109   5.309   0.000  1.00  0.00           N
ATOM     10  CA  SER B   3       3.609   6.609   0.000  1.00  0.00           C
ATOM     11  C   SER B   3       2.509   7.109   0.000  1.00  0.00           C
ATOM     12  O   SER B   3       1.509   6.409   0.000  1.00  0.00           O
END
"""


def _make_cand(cid: str, pdb_string: str) -> Candidate:
    return Candidate(candidate_id=cid, data=ProteinStructure(pdb_string=pdb_string))


class TestBatchTMScore:
    def test_scores_three_candidates(self) -> None:
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        cands = CandidateCollection(
            collection_id="coll",
            item_type="protein.structure",
            items=[
                _make_cand("c1", SAMPLE_PDB_3RES),
                _make_cand("c2", SAMPLE_PDB_SCALED),
                _make_cand("c3", SAMPLE_PDB_3RES),
            ],
        )

        result = mod.run({"reference": ref, "candidates": cands}, {}, ctx)
        scores = result["scores"]

        assert isinstance(scores, ScoreCollection)
        assert len(scores.entries) == 3
        for entry in scores.entries:
            assert entry.score_id == "tm_score"

    def test_identical_structure_tm_1(self) -> None:
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        cands = CandidateCollection(
            collection_id="coll",
            item_type="protein.structure",
            items=[_make_cand("c_self", SAMPLE_PDB_3RES)],
        )

        result = mod.run({"reference": ref, "candidates": cands}, {}, ctx)
        entry = result["scores"].entries[0]

        assert entry.value == pytest.approx(1.0, abs=0.01)
        assert entry.subjects == ["c_self"]

    def test_subjects_reference_candidate_ids(self) -> None:
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        cands = CandidateCollection(
            collection_id="coll",
            item_type="protein.structure",
            items=[
                _make_cand("alpha", SAMPLE_PDB_3RES),
                _make_cand("beta", SAMPLE_PDB_SCALED),
                _make_cand("gamma", SAMPLE_PDB_3RES),
            ],
        )

        result = mod.run({"reference": ref, "candidates": cands}, {}, ctx)
        subjects = [s.subjects[0] for s in result["scores"].entries]
        assert subjects == ["alpha", "beta", "gamma"]

    def test_empty_candidates_raises(self) -> None:
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        cands = CandidateCollection(
            collection_id="coll",
            item_type="protein.structure",
            items=[],
        )

        with pytest.raises(ValueError, match="empty"):
            mod.run({"reference": ref, "candidates": cands}, {}, ctx)

    def test_missing_reference_raises(self) -> None:
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        cands = CandidateCollection(
            collection_id="coll",
            item_type="protein.structure",
            items=[_make_cand("c1", SAMPLE_PDB_3RES)],
        )

        with pytest.raises(ValueError, match="reference"):
            mod.run({"candidates": cands}, {}, ctx)

    def test_missing_candidates_raises(self) -> None:
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)

        with pytest.raises(ValueError, match="candidates"):
            mod.run({"reference": ref}, {}, ctx)

    def test_wrong_item_type_raises(self) -> None:
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        cands = CandidateCollection(
            collection_id="coll",
            item_type="protein.sequence",
            items=[_make_cand("c1", SAMPLE_PDB_3RES)],
        )

        with pytest.raises(ValueError, match="item_type"):
            mod.run({"reference": ref, "candidates": cands}, {}, ctx)

    def test_different_chain_zero_score(self) -> None:
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)  # Chain A
        cands = CandidateCollection(
            collection_id="coll",
            item_type="protein.structure",
            items=[_make_cand("c_diff", DIFFERENT_CHAIN_PDB)],  # Chain B
        )

        result = mod.run({"reference": ref, "candidates": cands}, {}, ctx)
        entry = result["scores"].entries[0]

        assert entry.value == 0.0
        assert entry.details["aligned_residues"] == 0

    def test_scaled_structure_tm_below_1(self) -> None:
        """A 2x-scaled structure cannot be perfectly aligned, so TM < 1.0."""
        from modules.structure_batch_tm_score.module import BatchTMScoreModule
        mod = BatchTMScoreModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = ProteinStructure(pdb_string=SAMPLE_PDB_3RES)
        cands = CandidateCollection(
            collection_id="coll",
            item_type="protein.structure",
            items=[_make_cand("c_scaled", SAMPLE_PDB_SCALED)],
        )

        result = mod.run({"reference": ref, "candidates": cands}, {}, ctx)
        entry = result["scores"].entries[0]

        assert entry.value < 1.0
        assert entry.value > 0.0
        assert entry.details["aligned_residues"] == 3
