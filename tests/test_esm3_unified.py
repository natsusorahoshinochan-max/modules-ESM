"""Tests for unified esm3.generate module (ticket 15)."""

from unittest.mock import MagicMock, patch

import pytest
import torch

from core.run_context import RunContext
from datatypes import (
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
    ScoreCollection,
)
from tests.test_esm3 import _make_mock_esm_protein, _make_prompt


class TestESM3UnifiedGenerate:
    def test_effective_seed_controls_each_provider_call_rng(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_ep = _make_mock_esm_protein("AGS")
        def execute() -> tuple[list[float], dict[str, object]]:
            observed_rng_values: list[float] = []
            mock_client = MagicMock()

            def generate(protein, config):
                del protein, config
                observed_rng_values.append(float(torch.rand(1).item()))
                return mock_ep

            mock_client.generate.side_effect = generate
            with patch(
                "modules.esm3_adapter.create_esm3_client",
                return_value=mock_client,
            ):
                result = ESM3GenerateModule().run(
                    {"protein_prompt": _make_prompt(3)},
                    {
                        "model_name": "esm3_sm_open_v1",
                        "num_samples": 2,
                    },
                    RunContext(
                        "/tmp/test",
                        "n1",
                        run_id="seeded-run",
                        seed=1603,
                    ),
                )
            return observed_rng_values, result

        first_values, result = execute()
        second_values, _ = execute()
        assert first_values == second_values
        assert len(first_values) == 4
        assert len(set(first_values)) == 4
        assert ESM3GenerateModule.uses_seed is True
        for collection_name in (
            "sequence_candidates",
            "structure_candidates",
        ):
            metadata = [
                candidate.metadata
                for candidate in result[collection_name].items
            ]
            assert len({
                item["effective_seed"] for item in metadata
            }) == 2
            assert {
                item["requested_seed"] for item in metadata
            } == {1603}
            assert {
                item["seed_scope"] for item in metadata
            } == {"per_sample_track"}

    def test_remote_provider_does_not_claim_effective_seed(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_client = MagicMock()
        mock_client.generate.return_value = _make_mock_esm_protein("AGS")
        module = ESM3GenerateModule()
        with patch(
            "modules.esm3_adapter.create_esm3_client",
            return_value=mock_client,
        ):
            result = module.run(
                {"protein_prompt": _make_prompt(3)},
                {
                    "model_name": "esm3-medium-2024-08",
                    "num_samples": 1,
                },
                RunContext(
                    "/tmp/test",
                    "n1",
                    run_id="remote-run",
                    seed=1603,
                ),
            )

        assert module.uses_seed_for({
            "model_name": "esm3-medium-2024-08"
        }) is False
        for collection_name in (
            "sequence_candidates",
            "structure_candidates",
        ):
            metadata = result[collection_name].items[0].metadata
            assert metadata["requested_seed"] == 1603
            assert metadata["seed_control"] == "unsupported_by_provider"
            assert "effective_seed" not in metadata
            assert "seed_scope" not in metadata

    def test_outputs_both_sequence_and_structure(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_ep = _make_mock_esm_protein("AGS")
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 2},
                ctx,
            )

        seq_coll = result["sequence_candidates"]
        struct_coll = result["structure_candidates"]
        scores = result["scores"]

        # Both collections exist
        assert isinstance(seq_coll, CandidateCollection)
        assert isinstance(struct_coll, CandidateCollection)
        assert isinstance(scores, ScoreCollection)

        # Types
        assert seq_coll.item_type == "protein.sequence"
        assert struct_coll.item_type == "protein.structure"

        # Equal lengths
        assert len(seq_coll) == 2
        assert len(struct_coll) == 2

    def test_candidate_data_types(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_ep = _make_mock_esm_protein("AGS")
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 1},
                ctx,
            )

        seq_cand = result["sequence_candidates"].items[0]
        struct_cand = result["structure_candidates"].items[0]

        assert isinstance(seq_cand.data, ProteinSequence)
        assert seq_cand.data.sequence == "AGS"
        assert isinstance(struct_cand.data, ProteinStructure)
        assert "HEADER" in struct_cand.data.pdb_string

    def test_matched_indices_follow_sequence_then_structure_calls(self) -> None:
        """Verify that each structure is sampled from its same-index sequence."""
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_seq1 = _make_mock_esm_protein("ABC")
        mock_struct1 = _make_mock_esm_protein("ABC")
        mock_seq2 = _make_mock_esm_protein("XYZ")
        mock_struct2 = _make_mock_esm_protein("XYZ")
        mock_client = MagicMock()
        mock_client.generate.side_effect = [
            mock_seq1,
            mock_struct1,
            mock_seq2,
            mock_struct2,
        ]

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 2},
                ctx,
            )

        seq0 = result["sequence_candidates"].items[0]
        seq1 = result["sequence_candidates"].items[1]
        struct0 = result["structure_candidates"].items[0]
        struct1 = result["structure_candidates"].items[1]

        assert seq0.data.sequence == "ABC"
        assert seq1.data.sequence == "XYZ"
        assert seq0.metadata["sample_index"] == 0
        assert seq1.metadata["sample_index"] == 1
        assert struct0.metadata["sample_index"] == 0
        assert struct1.metadata["sample_index"] == 1

    def test_scores_output(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_ep = _make_mock_esm_protein("AGS", ptm=0.85, plddt_vals=[0.9, 0.8, 0.7])
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 2},
                ctx,
            )

        scores = result["scores"]
        # 2 samples × 2 score types (ptm + plddt) = 4 entries
        assert len(scores.entries) == 4
        ptm_entries = [s for s in scores.entries if s.score_id == "ptm"]
        plddt_entries = [s for s in scores.entries if s.score_id == "plddt"]
        assert len(ptm_entries) == 2
        assert len(plddt_entries) == 2
        for entry in ptm_entries:
            assert entry.value == pytest.approx(0.85)
        # Scores reference sequence candidates
        seq_ids = {c.candidate_id for c in result["sequence_candidates"].items}
        score_subjects = {s.subjects[0] for s in scores.entries if s.subjects}
        assert score_subjects.issubset(seq_ids)

    def test_classification_absent_without_template(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_ep = _make_mock_esm_protein()
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3, with_structure=False)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 1},
                ctx,
            )

        seq_c = result["sequence_candidates"].items[0]
        struct_c = result["structure_candidates"].items[0]
        assert seq_c.metadata["classification"] == "absent"
        assert struct_c.metadata["classification"] == "sampled_structure"

    def test_classification_reconstruction_with_template(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_ep = _make_mock_esm_protein()
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3, with_structure=True)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 1},
                ctx,
            )

        seq_c = result["sequence_candidates"].items[0]
        struct_c = result["structure_candidates"].items[0]
        assert seq_c.metadata["classification"] == "prompt_reconstruction"
        assert struct_c.metadata["classification"] == "sampled_structure"

    def test_missing_prompt_raises(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mod = ESM3GenerateModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="protein_prompt"):
            mod.run({}, {}, ctx)

    def test_single_sample(self) -> None:
        from modules.esm3_generate.module import ESM3GenerateModule

        mock_ep = _make_mock_esm_protein("AGS")
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 1},
                ctx,
            )

        assert len(result["sequence_candidates"]) == 1
        assert len(result["structure_candidates"]) == 1
        # Scores: 1 ptm + 1 plddt
        assert len(result["scores"].entries) == 2
