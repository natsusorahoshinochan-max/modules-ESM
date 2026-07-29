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
    def test_v2_all_modes_and_ten_pairs(
        self,
        readiness,
        pdb_3gb1,
        tmp_path,
    ):
        """Required remote gate for all cohesive v2 ESM-3 operations."""
        require_ready("biohub", readiness)

        from modules.esm3_adapter import create_esm3_client
        from modules.extract_sequence_from_structure.module import (
            _extract_sequence,
        )
        from tests.test_esm3_v2 import _decode_output, _run_generation

        sequence = _extract_sequence(pdb_3gb1.pdb_string)
        assert len(sequence) == 56
        client = create_esm3_client("esm3-medium-2024-08")
        parameters = {"num_steps": 1}

        _, sequence_projection, _ = _run_generation(
            tmp_path / "sequence",
            operation="generate_sequence",
            client=client,
            num_samples=1,
            sequence=sequence,
            generation_parameters=parameters,
            sequence_mask_residue_ids=("A:1",),
        )
        assert sequence_projection["status"] == "succeeded"

        _, structure_projection, _ = _run_generation(
            tmp_path / "structure",
            operation="generate_structure",
            client=client,
            num_samples=1,
            sequence=sequence,
            generation_parameters=parameters,
        )
        assert structure_projection["status"] == "succeeded"

        catalog, paired_projection, _ = _run_generation(
            tmp_path / "paired",
            operation="generate_paired",
            client=client,
            num_samples=10,
            sequence=sequence,
            generation_parameters=parameters,
            sequence_mask_residue_ids=("A:1",),
        )
        assert paired_projection["status"] == "succeeded"
        paired_outputs = {
            output["output_port"]: output
            for output in paired_projection["outputs"]
            if output["node_id"] == "generate"
        }
        sequences = _decode_output(
            catalog,
            paired_outputs["sequence_candidates"],
        )
        structures = _decode_output(
            catalog,
            paired_outputs["structure_candidates"],
        )
        pairs = _decode_output(
            catalog,
            paired_outputs["counterpart_pairs"],
        )
        assert len(sequences.items) == len(structures.items) == 10
        assert len(pairs.entries) == 10

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
