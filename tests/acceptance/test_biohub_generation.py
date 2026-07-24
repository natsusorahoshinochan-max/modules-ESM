"""Acceptance: ESM3 sequence generation via Biohub."""

import pytest

from core.run_context import RunContext
from datatypes import CandidateCollection, ProteinSequence
from tests.acceptance.conftest import require_ready


@pytest.mark.acceptance
class TestBiohubGeneration:
    def test_generate_3gb1_sequence(self, readiness, pdb_3gb1):
        require_ready("biohub", readiness)

        from modules import esm3_adapter
        from modules.extract_sequence_from_structure.module import _extract_sequence

        seq_str = _extract_sequence(pdb_3gb1.pdb_string)
        assert len(seq_str) == 56, f"Expected 56 residues, got {len(seq_str)}"

        seq = ProteinSequence(sequence=seq_str)
        ctx = RunContext("/tmp/acceptance-test", "n1")

        model_name = "esm3-medium-2024-08"
        client = esm3_adapter.create_esm3_client(model_name, ctx.project_dir)

        from esm.sdk.api import GenerationConfig, ESMProtein as ESMProteinSDK

        prompt = ESMProteinSDK(sequence=seq_str)
        config = GenerationConfig(track="sequence", num_steps=8, temperature=0.7)

        result = client.generate(prompt, config)
        gen_seq = esm3_adapter.esm_protein_to_sequence(result)

        assert isinstance(gen_seq, ProteinSequence)
        assert len(gen_seq.sequence) == 56

        scores = esm3_adapter.esm_protein_to_scores(result, "test-cid")
        assert any(s.score_id == "ptm" for s in scores.entries)
        assert any(s.score_id == "plddt" for s in scores.entries)

    def test_generate_1pga_sequence(self, readiness, pdb_1pga):
        require_ready("biohub", readiness)

        from modules import esm3_adapter
        from modules.extract_sequence_from_structure.module import _extract_sequence

        seq_str = _extract_sequence(pdb_1pga.pdb_string)
        assert len(seq_str) == 75

        seq = ProteinSequence(sequence=seq_str)
        ctx = RunContext("/tmp/acceptance-test", "n1")

        model_name = "esm3-medium-2024-08"
        client = esm3_adapter.create_esm3_client(model_name, ctx.project_dir)

        from esm.sdk.api import GenerationConfig, ESMProtein as ESMProteinSDK

        prompt = ESMProteinSDK(sequence=seq_str)
        config = GenerationConfig(track="sequence", num_steps=8, temperature=0.7)

        result = client.generate(prompt, config)
        gen_seq = esm3_adapter.esm_protein_to_sequence(result)

        assert isinstance(gen_seq, ProteinSequence)
        assert len(gen_seq.sequence) == 75

        scores = esm3_adapter.esm_protein_to_scores(result, "test-cid")
        assert any(s.score_id == "ptm" for s in scores.entries)
