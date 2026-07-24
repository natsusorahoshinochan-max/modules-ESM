"""Tests for ESM3 generation modules (ticket 06)."""

import json
from unittest.mock import MagicMock, patch

import torch
import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    FunctionAnnotations,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ResidueTrack,
    Score,
    ScoreCollection,
)

# ── Shared test data ─────────────────────────────────────────────────

def _make_prompt(length: int = 3, with_structure: bool = False) -> ProteinPrompt:
    layout = ResidueLayout(chain_id="A", length=length)
    seq = ResidueTrack(values=["A", "G", "S"][:length], sentinel=None)
    struct = None
    vis = None
    if with_structure:
        struct = ResidueTrack(
            values=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)][:length],
            sentinel=None,
        )
        vis = ResidueTrack(values=[True] * length, sentinel=None)
    ss = ResidueTrack(values=["H", "E", "-"][:length], sentinel=None)
    sasa = ResidueTrack(values=[50.0, 75.0, 100.0][:length], sentinel=None)
    fa = FunctionAnnotations()
    fa.add("active_site", 1, 2)
    return ProteinPrompt(
        target_layout=layout,
        sequence_track=seq,
        structure_track=struct,
        structure_visibility_track=vis,
        secondary_structure_track=ss,
        sasa_track=sasa,
        function_annotations=fa,
    )


def _make_mock_esm_protein(sequence: str = "AGS", ptm: float = 0.85,
                            plddt_vals: list[float] | None = None) -> MagicMock:
    """Create a mock ESMProtein with set attributes."""
    mock = MagicMock()
    mock.sequence = sequence
    mock.ptm = torch.tensor([ptm])
    if plddt_vals is None:
        plddt_vals = [0.9, 0.8, 0.7]
    mock.plddt = torch.tensor(plddt_vals)
    mock.to_pdb_string.return_value = (
        "HEADER    MOCK\n"
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00\n"
        "END\n"
    )
    return mock


# ── ESM3 Adapter ─────────────────────────────────────────────────────

class TestESM3Adapter:
    def test_prompt_to_esm_protein_basic(self) -> None:
        from modules.esm3_adapter import protein_prompt_to_esm_protein
        prompt = _make_prompt(3)
        ep = protein_prompt_to_esm_protein(prompt)
        assert ep.sequence == "AGS"
        assert ep.secondary_structure == "HE-"
        assert ep.sasa == [50.0, 75.0, 100.0]
        assert ep.function_annotations is not None
        assert len(ep.function_annotations) == 1
        assert ep.coordinates is None  # no structure track

    def test_prompt_with_coordinates(self) -> None:
        from modules.esm3_adapter import protein_prompt_to_esm_protein
        prompt = _make_prompt(3, with_structure=True)
        ep = protein_prompt_to_esm_protein(prompt)
        assert ep.coordinates is not None
        assert ep.coordinates.shape == (3, 37, 3)
        # CA at position 1 in atom37
        assert ep.coordinates[0, 1, 0].item() == 1.0

    def test_empty_prompt_raises(self) -> None:
        from modules.esm3_adapter import protein_prompt_to_esm_protein
        prompt = ProteinPrompt()
        with pytest.raises(ValueError, match="num_residues"):
            protein_prompt_to_esm_protein(prompt)

    def test_prompt_with_none_tracks(self) -> None:
        from modules.esm3_adapter import protein_prompt_to_esm_protein
        layout = ResidueLayout(chain_id="A", length=2)
        prompt = ProteinPrompt(target_layout=layout)
        ep = protein_prompt_to_esm_protein(prompt)
        assert ep.sequence == "__"
        assert ep.secondary_structure is None
        assert ep.sasa is None

    def test_esm_protein_to_sequence(self) -> None:
        from modules.esm3_adapter import esm_protein_to_sequence
        mock = _make_mock_esm_protein("MKFLIL")
        seq = esm_protein_to_sequence(mock)
        assert isinstance(seq, ProteinSequence)
        assert seq.sequence == "MKFLIL"

    def test_esm_protein_to_sequence_missing_raises(self) -> None:
        from modules.esm3_adapter import esm_protein_to_sequence
        mock = MagicMock()
        mock.sequence = None
        with pytest.raises(ValueError, match="no sequence"):
            esm_protein_to_sequence(mock)

    def test_esm_protein_to_structure(self) -> None:
        from modules.esm3_adapter import esm_protein_to_structure
        mock = _make_mock_esm_protein()
        struct = esm_protein_to_structure(mock)
        assert isinstance(struct, ProteinStructure)
        assert "HEADER" in struct.pdb_string

    def test_esm_protein_to_scores_ptm_normalization(self) -> None:
        from modules.esm3_adapter import esm_protein_to_scores
        mock = _make_mock_esm_protein(ptm=0.85)
        scores = esm_protein_to_scores(mock, "test-cid")
        assert isinstance(scores, ScoreCollection)
        ptm_entry = [s for s in scores.entries if s.score_id == "ptm"]
        assert len(ptm_entry) == 1
        assert ptm_entry[0].value == pytest.approx(0.85)

    def test_esm_protein_to_scores_plddt_mean(self) -> None:
        from modules.esm3_adapter import esm_protein_to_scores
        mock = _make_mock_esm_protein(plddt_vals=[0.5, 0.7, 0.9])
        scores = esm_protein_to_scores(mock, "test-cid")
        plddt_entry = [s for s in scores.entries if s.score_id == "plddt"]
        assert len(plddt_entry) == 1
        assert abs(plddt_entry[0].value - 0.7) < 0.01

    def test_read_biohub_token_found(self) -> None:
        from modules.esm3_adapter import read_biohub_token
        token = read_biohub_token()
        assert isinstance(token, str)
        assert len(token) > 0


# ── Update Prompt Sequence ───────────────────────────────────────────

class TestUpdatePromptSequence:
    def test_replaces_sequence_preserves_others(self) -> None:
        from modules.esm3_update_prompt_sequence.module import UpdatePromptSequenceModule
        mod = UpdatePromptSequenceModule()
        ctx = RunContext("/tmp/test", "n1")
        prompt = _make_prompt(3)
        new_seq = ProteinSequence(sequence="WFC")
        result = mod.run(
            {"protein_prompt": prompt, "sequence": new_seq},
            {},
            ctx,
        )
        updated = result["protein_prompt"]
        assert isinstance(updated, ProteinPrompt)
        assert updated.sequence_track.values == ["W", "F", "C"]
        # All other tracks preserved
        assert updated.secondary_structure_track.values == ["H", "E", "-"]
        assert updated.sasa_track.values == [50.0, 75.0, 100.0]
        assert updated.structure_track is None
        assert len(updated.function_annotations) == 1

    def test_preserves_structure_coordinates(self) -> None:
        from modules.esm3_update_prompt_sequence.module import UpdatePromptSequenceModule
        mod = UpdatePromptSequenceModule()
        ctx = RunContext("/tmp/test", "n1")
        prompt = _make_prompt(3, with_structure=True)
        new_seq = ProteinSequence(sequence="WFC")
        result = mod.run(
            {"protein_prompt": prompt, "sequence": new_seq},
            {},
            ctx,
        )
        updated = result["protein_prompt"]
        assert updated.structure_track is not None
        assert updated.structure_visibility_track is not None

    def test_mismatched_length_raises(self) -> None:
        from modules.esm3_update_prompt_sequence.module import UpdatePromptSequenceModule
        mod = UpdatePromptSequenceModule()
        ctx = RunContext("/tmp/test", "n1")
        prompt = _make_prompt(3)
        new_seq = ProteinSequence(sequence="AAAA")  # length 4
        with pytest.raises(ValueError, match="length"):
            mod.run(
                {"protein_prompt": prompt, "sequence": new_seq},
                {},
                ctx,
            )

    def test_missing_prompt_raises(self) -> None:
        from modules.esm3_update_prompt_sequence.module import UpdatePromptSequenceModule
        mod = UpdatePromptSequenceModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="protein_prompt"):
            mod.run({}, {}, ctx)


# ── ESM3 Generate Sequence (mocked) ───────────────────────────────────

class TestESM3GenerateSequence:
    def test_generates_candidates(self) -> None:
        from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule
        mock_ep = _make_mock_esm_protein("AGS")
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateSequenceModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 2, "model_name": "esm3-medium-2024-08"},
                ctx,
            )

        candidates = result["candidates"]
        assert isinstance(candidates, CandidateCollection)
        assert len(candidates) == 2
        assert candidates.item_type == "protein.sequence"
        for c in candidates:
            assert isinstance(c.data, ProteinSequence)
            assert c.data.sequence == "AGS"
            assert c.metadata["classification"] == "absent"

        scores = result["scores"]
        assert isinstance(scores, ScoreCollection)
        assert len(scores.entries) == 4  # 2 pTM + 2 pLDDT

    def test_missing_prompt_raises(self) -> None:
        from modules.esm3_generate_sequence.module import ESM3GenerateSequenceModule
        mod = ESM3GenerateSequenceModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="protein_prompt"):
            mod.run({}, {}, ctx)


# ── ESM3 Generate Structure (mocked) ──────────────────────────────────

class TestESM3GenerateStructure:
    def test_generates_without_template_coords(self) -> None:
        from modules.esm3_generate_structure.module import ESM3GenerateStructureModule
        mock_ep = _make_mock_esm_protein()
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateStructureModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3, with_structure=False)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 1},
                ctx,
            )

        candidates = result["candidates"]
        assert len(candidates) == 1
        c = candidates.items[0]
        assert c.metadata["classification"] == "absent"
        assert isinstance(c.data, ProteinStructure)
        assert "HEADER" in c.data.pdb_string

    def test_generates_with_template_coords(self) -> None:
        from modules.esm3_generate_structure.module import ESM3GenerateStructureModule
        mock_ep = _make_mock_esm_protein()
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ep

        with (
            patch("modules.esm3_adapter.create_esm3_client", return_value=mock_client),
        ):
            mod = ESM3GenerateStructureModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            prompt = _make_prompt(3, with_structure=True)
            result = mod.run(
                {"protein_prompt": prompt},
                {"num_samples": 1},
                ctx,
            )

        c = result["candidates"].items[0]
        assert c.metadata["classification"] == "prompt_reconstruction"

    def test_missing_prompt_raises(self) -> None:
        from modules.esm3_generate_structure.module import ESM3GenerateStructureModule
        mod = ESM3GenerateStructureModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="protein_prompt"):
            mod.run({}, {}, ctx)


# ── Module Discovery ─────────────────────────────────────────────────

class TestModuleDiscoveryE2E:
    def test_38_modules_discoverable(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        ids = {m.module_id for m in mr.list_all()}
        expected_esm3 = {
            "esm3.generate_sequence",
            "esm3.update_prompt_sequence",
            "esm3.generate_structure",
        }
        assert expected_esm3.issubset(ids)
        assert len(mr) == 39

    def test_all_types_registered(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        types = set(tr.list_all())
        for tid in ["candidate.collection", "score.collection"]:
            assert tid in types, f"Missing type: {tid}"
