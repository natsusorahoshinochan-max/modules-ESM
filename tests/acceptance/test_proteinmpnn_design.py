"""Acceptance: ProteinMPNN sequence design (local)."""

import pytest

from datatypes import ProteinSequence
from tests.acceptance.conftest import require_ready


@pytest.mark.acceptance
@pytest.mark.local_provider
@pytest.mark.slow
class TestProteinMPNNDesign:
    def test_design_3gb1(self, readiness, pdb_3gb1, record_provider_call):
        require_ready("proteinmpnn", readiness)

        from modules.proteinmpnn.adapter import design_sequences

        sequences, avg_score = design_sequences(
            pdb_string=pdb_3gb1.pdb_string,
            model_name="v_48_020",
            num_sequences=2,
            temperature=0.1,
        )
        record_provider_call("proteinmpnn", "design_sequences")

        assert len(sequences) == 2
        for seq in sequences:
            assert isinstance(seq, ProteinSequence)
            assert len(seq.sequence) == 56

        assert avg_score is not None

    def test_design_1pga(self, readiness, pdb_1pga, record_provider_call):
        require_ready("proteinmpnn", readiness)

        from modules.proteinmpnn.adapter import design_sequences

        sequences, avg_score = design_sequences(
            pdb_string=pdb_1pga.pdb_string,
            model_name="v_48_020",
            num_sequences=2,
            temperature=0.1,
        )
        record_provider_call("proteinmpnn", "design_sequences")

        assert len(sequences) == 2
        for seq in sequences:
            assert isinstance(seq, ProteinSequence)
            assert len(seq.sequence) == 75

        assert avg_score is not None
