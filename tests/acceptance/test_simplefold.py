"""Acceptance: SimpleFold folding and evaluation (local)."""

import pytest

from datatypes import ProteinSequence, ProteinStructure, ScoreCollection
from tests.acceptance.conftest import require_ready


@pytest.mark.acceptance
@pytest.mark.slow
class TestSimpleFold:
    def test_fold_3gb1(self, readiness, pdb_3gb1):
        require_ready("simplefold", readiness)

        from modules.extract_sequence_from_structure.module import _extract_sequence
        from modules.simplefold_adapter import fold_sequence

        seq_str = _extract_sequence(pdb_3gb1.pdb_string)
        seq = ProteinSequence(sequence=seq_str)

        structures, scores = fold_sequence(
            sequence=seq,
            model_name="simplefold_100M",
            num_steps=10,
            num_samples=1,
        )

        assert len(structures) == 1
        struct = structures[0]
        assert isinstance(struct, ProteinStructure)
        assert len(struct.pdb_string) > 0

        assert isinstance(scores, ScoreCollection)
        plddt_entries = [s for s in scores.entries if s.score_id == "plddt"]
        assert len(plddt_entries) >= 1
        assert 0.0 <= plddt_entries[0].value <= 100.0

    def test_fold_1pga(self, readiness, pdb_1pga):
        require_ready("simplefold", readiness)

        from modules.extract_sequence_from_structure.module import _extract_sequence
        from modules.simplefold_adapter import fold_sequence

        seq_str = _extract_sequence(pdb_1pga.pdb_string)
        seq = ProteinSequence(sequence=seq_str)

        structures, scores = fold_sequence(
            sequence=seq,
            model_name="simplefold_100M",
            num_steps=10,
            num_samples=1,
        )

        assert len(structures) == 1
        struct = structures[0]
        assert isinstance(struct, ProteinStructure)
        assert len(struct.pdb_string) > 0

        assert isinstance(scores, ScoreCollection)
        plddt_entries = [s for s in scores.entries if s.score_id == "plddt"]
        assert len(plddt_entries) >= 1
        assert 0.0 <= plddt_entries[0].value <= 100.0

    def test_evaluate_3gb1(self, readiness, pdb_3gb1):
        require_ready("simplefold", readiness)

        from modules.simplefold_adapter import evaluate_structure

        scores = evaluate_structure(
            structure=pdb_3gb1,
            model_name="simplefold_360M",
        )

        assert isinstance(scores, ScoreCollection)
        plddt_entries = [s for s in scores.entries if s.score_id == "plddt"]
        assert len(plddt_entries) >= 1
        assert 0.0 <= plddt_entries[0].value <= 100.0

    def test_evaluate_1pga(self, readiness, pdb_1pga):
        require_ready("simplefold", readiness)

        from modules.simplefold_adapter import evaluate_structure

        scores = evaluate_structure(
            structure=pdb_1pga,
            model_name="simplefold_360M",
        )

        assert isinstance(scores, ScoreCollection)
        plddt_entries = [s for s in scores.entries if s.score_id == "plddt"]
        assert len(plddt_entries) >= 1
        assert 0.0 <= plddt_entries[0].value <= 100.0
