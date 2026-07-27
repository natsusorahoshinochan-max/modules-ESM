"""Acceptance: ESMFold2 folding via Biohub."""

import hashlib
from pathlib import Path

import pytest

from datatypes import ProteinSequence, ProteinStructure, ScoreCollection
from tests.acceptance.conftest import SEQUENCE_3GB1_SHA256, require_ready


@pytest.mark.acceptance
@pytest.mark.live_provider
class TestBiohubFolding:
    @pytest.mark.parametrize("include_pae,include_embeddings", [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ])
    def test_fold_3gb1(
        self, readiness, include_pae, include_embeddings
    ):
        require_ready("biohub", readiness)

        from modules.esmfold2_adapter import fold_sequence

        seq = ProteinSequence(
            sequence="MTYKLILNGKTLKGETTTEAVDAATAEKVFKQYANDNGVDGEWTYDDATKTFTVTE"
        )
        assert len(seq) == 56
        assert (
            hashlib.sha256(seq.sequence.encode()).hexdigest()
            == SEQUENCE_3GB1_SHA256
        )

        structure, scores = fold_sequence(
            sequence=seq,
            model_name="esmfold2-fast-2026-05",
            include_pae=include_pae,
            include_embeddings=include_embeddings,
        )

        assert isinstance(structure, ProteinStructure)
        assert len(structure.pdb_string) > 0
        assert isinstance(scores, ScoreCollection)

        # pTM and pLDDT should always be present
        assert any(s.score_id == "ptm" for s in scores.entries)
        assert any(s.score_id == "plddt" for s in scores.entries)

        if include_pae:
            assert any(s.score_id == "pae" for s in scores.entries)
        if include_embeddings:
            assert any(s.score_id == "embedding_pair_pooled" for s in scores.entries)

    @pytest.mark.parametrize("include_pae,include_embeddings", [
        (False, False),
        (True, False),
    ])
    def test_fold_1pga(
        self, readiness, include_pae, include_embeddings
    ):
        require_ready("biohub", readiness)

        from modules.esmfold2_adapter import fold_sequence

        from modules.extract_sequence_from_structure.module import _extract_sequence
        seq_str = _extract_sequence(
            (
                Path(__file__).parents[2]
                / "pdbs"
                / "1PGA-75-gen1_0690.pdb"
            ).read_text()
        )

        seq = ProteinSequence(sequence=seq_str)
        assert len(seq) == 75

        structure, scores = fold_sequence(
            sequence=seq,
            model_name="esmfold2-fast-2026-05",
            include_pae=include_pae,
            include_embeddings=include_embeddings,
        )

        assert isinstance(structure, ProteinStructure)
        assert any(s.score_id == "ptm" for s in scores.entries)
