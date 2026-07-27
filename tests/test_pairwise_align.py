"""Tests for structure.pairwise_align module (ticket 18a)."""

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinStructure,
    StructureAlignment,
)

# ── PDB fixtures ──────────────────────────────────────────────────────

SAMPLE_PDB_3RES_A = """\
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

# Scaled 2x — same residue identities, different coordinates
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

# Different chain ID — no common residues with chain A
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


def _make_coll(
    cid: str, item_type: str, candidates: list[Candidate],
) -> CandidateCollection:
    return CandidateCollection(
        collection_id=cid, item_type=item_type, items=candidates,
    )


class TestPairwiseAlign:
    def test_equal_length_collections(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("r1", SAMPLE_PDB_3RES_A),
            _make_cand("r2", SAMPLE_PDB_3RES_A),
            _make_cand("r3", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("m1", SAMPLE_PDB_SCALED),
            _make_cand("m2", SAMPLE_PDB_SCALED),
            _make_cand("m3", SAMPLE_PDB_SCALED),
        ])

        result = mod.run(
            {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
        )
        alignments = result["alignments"]

        assert isinstance(alignments, CandidateCollection)
        assert alignments.item_type == "structure.alignment"
        assert len(alignments) == 3

    def test_candidate_id_preservation(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("alpha", SAMPLE_PDB_3RES_A),
            _make_cand("beta", SAMPLE_PDB_3RES_A),
            _make_cand("gamma", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("x1", SAMPLE_PDB_SCALED),
            _make_cand("x2", SAMPLE_PDB_SCALED),
            _make_cand("x3", SAMPLE_PDB_SCALED),
        ])

        result = mod.run(
            {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
        )
        alignments = result["alignments"]

        assert alignments.items[0].candidate_id == "alpha"
        assert alignments.items[1].candidate_id == "beta"
        assert alignments.items[2].candidate_id == "gamma"

    def test_identical_structures_rmsd_zero(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("self", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("self_mob", SAMPLE_PDB_3RES_A),
        ])

        result = mod.run(
            {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
        )
        alignment_cand = result["alignments"].items[0]
        alignment = alignment_cand.data

        assert isinstance(alignment, StructureAlignment)
        assert alignment.rmsd == pytest.approx(0.0, abs=0.01)
        assert alignment.coverage == pytest.approx(1.0, abs=0.01)

    def test_scaled_structure_nonzero_rmsd(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("r1", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("m1", SAMPLE_PDB_SCALED),
        ])

        result = mod.run(
            {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
        )
        alignment = result["alignments"].items[0].data

        assert alignment.rmsd > 0.0
        assert alignment.coverage == pytest.approx(1.0, abs=0.01)

    def test_mismatched_lengths_raises(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("r1", SAMPLE_PDB_3RES_A),
            _make_cand("r2", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("m1", SAMPLE_PDB_SCALED),
        ])

        with pytest.raises(ValueError, match="equal length"):
            mod.run(
                {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
            )

    def test_empty_reference_raises(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("m1", SAMPLE_PDB_SCALED),
        ])

        with pytest.raises(ValueError, match="empty"):
            mod.run(
                {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
            )

    def test_empty_mobile_raises(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("r1", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [])

        with pytest.raises(ValueError, match="empty"):
            mod.run(
                {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
            )

    def test_missing_reference_raises(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        mob = _make_coll("mob", "protein.structure", [
            _make_cand("m1", SAMPLE_PDB_SCALED),
        ])

        with pytest.raises(ValueError, match="reference_candidates"):
            mod.run({"mobile_candidates": mob}, {}, ctx)

    def test_missing_mobile_raises(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("r1", SAMPLE_PDB_3RES_A),
        ])

        with pytest.raises(ValueError, match="mobile_candidates"):
            mod.run({"reference_candidates": ref}, {}, ctx)

    def test_different_chain_preserves_sequence_correspondence(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("r1", SAMPLE_PDB_3RES_A),  # Chain A
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("m1", DIFFERENT_CHAIN_PDB),  # Chain B
        ])

        result = mod.run(
            {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
        )
        alignment = result["alignments"].items[0].data

        assert alignment.coverage == pytest.approx(1.0)
        assert alignment.chain_map == {"A": "B"}
        assert alignment.residue_map == [
            ("A:1", "B:1"),
            ("A:2", "B:2"),
            ("A:3", "B:3"),
        ]

    def test_data_is_structure_alignment(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("r1", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("m1", SAMPLE_PDB_SCALED),
        ])

        result = mod.run(
            {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
        )
        alignment_cand = result["alignments"].items[0]

        assert isinstance(alignment_cand.data, StructureAlignment)
        assert hasattr(alignment_cand.data, "rotation")
        assert hasattr(alignment_cand.data, "translation")
        assert hasattr(alignment_cand.data, "rmsd")
        assert hasattr(alignment_cand.data, "coverage")
        assert hasattr(alignment_cand.data, "residue_map")

    def test_wrong_item_type_raises(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.sequence", [
            _make_cand("r1", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("m1", SAMPLE_PDB_SCALED),
        ])

        with pytest.raises(ValueError, match="item_type"):
            mod.run(
                {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
            )

    def test_single_pair_output_count(self) -> None:
        from modules.structure_pairwise_align.module import PairwiseAlignModule
        mod = PairwiseAlignModule()
        ctx = RunContext("/tmp/test", "n1")

        ref = _make_coll("ref", "protein.structure", [
            _make_cand("only", SAMPLE_PDB_3RES_A),
        ])
        mob = _make_coll("mob", "protein.structure", [
            _make_cand("only_mob", SAMPLE_PDB_SCALED),
        ])

        result = mod.run(
            {"reference_candidates": ref, "mobile_candidates": mob}, {}, ctx
        )
        assert len(result["alignments"]) == 1
