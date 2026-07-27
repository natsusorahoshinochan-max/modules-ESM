"""Acceptance: ESM3 sequence generation via Biohub."""

import hashlib
import pytest

from core.run_context import RunContext
from datatypes import (
    CandidateCollection,
    ProteinPrompt,
    ProteinSequence,
    ResidueLayout,
    ResidueTrack,
)
from tests.acceptance.conftest import SEQUENCE_3GB1_SHA256, require_ready


def _make_prompt(seq_str: str) -> ProteinPrompt:
    """Create a ProteinPrompt with masked position 0 so ESM3 has something to generate."""
    n = len(seq_str)
    layout = ResidueLayout(chain_id="A", length=n)
    # Mask first position so ESM3 generates it
    values = list(seq_str)
    values[0] = None  # sentinel = masked
    seq_track = ResidueTrack(values=values, sentinel=None)
    return ProteinPrompt(target_layout=layout, sequence_track=seq_track)


@pytest.mark.acceptance
@pytest.mark.live_provider
class TestBiohubGeneration:
    def test_generate_3gb1_sequence(
        self, readiness, pdb_3gb1, isolated_project_dir
    ):
        require_ready("biohub", readiness)

        from modules.extract_sequence_from_structure.module import _extract_sequence

        seq_str = _extract_sequence(pdb_3gb1.pdb_string)
        assert len(seq_str) == 56, f"Expected 56 residues, got {len(seq_str)}"
        assert hashlib.sha256(seq_str.encode()).hexdigest() == SEQUENCE_3GB1_SHA256

        prompt = _make_prompt(seq_str)

        from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule
        mod = ESM3GenerateSequenceModule()
        ctx = RunContext(isolated_project_dir, "n1", run_id="acc-3gb1")

        result = mod.run(
            {"protein_prompt": prompt},
            {"model_name": "esm3-medium-2024-08", "num_steps": 8,
             "temperature": 0.7, "num_samples": 1},
            ctx,
        )

        candidates = result["candidates"]
        assert isinstance(candidates, CandidateCollection)
        assert len(candidates) == 1
        c = candidates.items[0]
        assert isinstance(c.data, ProteinSequence)
        assert len(c.data.sequence) == 56

        scores = result["scores"]
        from datatypes import ScoreCollection
        assert isinstance(scores, ScoreCollection)
        # Sequence-only generation may or may not include confidence scores;
        # verify at minimum that scores is a valid collection

    def test_generate_1pga_sequence(
        self, readiness, pdb_1pga, isolated_project_dir
    ):
        require_ready("biohub", readiness)

        from modules.extract_sequence_from_structure.module import _extract_sequence

        seq_str = _extract_sequence(pdb_1pga.pdb_string)
        assert len(seq_str) == 75

        prompt = _make_prompt(seq_str)

        from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule
        mod = ESM3GenerateSequenceModule()
        ctx = RunContext(isolated_project_dir, "n1", run_id="acc-1pga")

        result = mod.run(
            {"protein_prompt": prompt},
            {"model_name": "esm3-medium-2024-08", "num_steps": 8,
             "temperature": 0.7, "num_samples": 1},
            ctx,
        )

        candidates = result["candidates"]
        assert isinstance(candidates, CandidateCollection)
        assert len(candidates) == 1
        c = candidates.items[0]
        assert isinstance(c.data, ProteinSequence)
        assert len(c.data.sequence) == 75

        scores = result["scores"]
        from datatypes import ScoreCollection
        assert isinstance(scores, ScoreCollection)
