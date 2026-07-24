"""Tests for ProteinMPNN modules (ticket 07)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)

SAMPLE_PDB = """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA A   1       2.009   1.421   0.000  1.00  0.00           C
ATOM      4  O   ALA A   1       1.223   2.371   0.000  1.00  0.00           O
ATOM      5  N   GLY A   2       3.309   1.681   0.000  1.00  0.00           N
ATOM      6  CA  GLY A   2       3.909   3.009   0.000  1.00  0.00           C
ATOM      7  C   GLY A   2       3.309   4.309   0.000  1.00  0.00           C
ATOM      8  O   GLY A   2       2.109   4.409   0.000  1.00  0.00           O
END
"""


# ── Constraints Module ───────────────────────────────────────────────

class TestConstraintsModule:
    def test_default_empty_constraints(self) -> None:
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule
        mod = ProteinMPNNConstraintsModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {}, ctx)
        c = result["constraints"]
        assert isinstance(c, ProteinMPNNConstraints)
        assert c.designable_positions is None
        assert c.fixed_positions is None

    def test_parses_fixed_positions(self) -> None:
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule
        mod = ProteinMPNNConstraintsModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {"fixed_positions": "[1, 5, 10]"}, ctx)
        c = result["constraints"]
        assert c.fixed_positions == [1, 5, 10]

    def test_parses_omit_amino_acids(self) -> None:
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule
        mod = ProteinMPNNConstraintsModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {"omit_amino_acids": '["C", "M"]'}, ctx)
        c = result["constraints"]
        assert c.omit_amino_acids == ["C", "M"]

    def test_empty_string_yields_none(self) -> None:
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule
        mod = ProteinMPNNConstraintsModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {"fixed_positions": ""}, ctx)
        assert result["constraints"].fixed_positions is None

    def test_empty_json_array_yields_none(self) -> None:
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule
        mod = ProteinMPNNConstraintsModule()
        ctx = RunContext("/tmp/test", "n1")
        result = mod.run({}, {"fixed_positions": "[]"}, ctx)
        assert result["constraints"].fixed_positions is None


# ── ProteinMPNN Design (mocked adapter) ──────────────────────────────

class TestProteinMPNNDesign:
    def test_design_produces_candidates(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        mock_seq = ProteinSequence(sequence="AGSWFC")
        with patch(
            "modules.proteinmpnn.module_design.design_sequences",
            return_value=([mock_seq, mock_seq], -1.5),
        ):
            mod = ProteinMPNNDesignModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            ps = ProteinStructure(pdb_string=SAMPLE_PDB)
            result = mod.run(
                {"structure": ps},
                {"num_sequences": 2},
                ctx,
            )

        candidates = result["candidates"]
        assert isinstance(candidates, CandidateCollection)
        assert len(candidates) == 2
        assert candidates.item_type == "protein.sequence"
        assert candidates.items[0].data.sequence == "AGSWFC"

        scores = result["scores"]
        assert isinstance(scores, ScoreCollection)
        assert len(scores.entries) == 1
        assert scores.entries[0].score_id == "proteinmpnn_score"

    def test_passes_constraints(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        mock_seq = ProteinSequence(sequence="AAAA")
        constraints = ProteinMPNNConstraints(fixed_positions=[1, 2, 3])

        with patch(
            "modules.proteinmpnn.module_design.design_sequences",
            return_value=([mock_seq], -2.0),
        ) as mock_design:
            mod = ProteinMPNNDesignModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            ps = ProteinStructure(pdb_string=SAMPLE_PDB)
            mod.run(
                {"structure": ps, "constraints": constraints},
                {"num_sequences": 1},
                ctx,
            )
            # Verify constraints were passed through
            call_kwargs = mock_design.call_args[1]
            passed_constraints = call_kwargs.get("constraints")
            assert passed_constraints is not None
            assert passed_constraints.fixed_positions == [1, 2, 3]

    def test_missing_structure_raises(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
        mod = ProteinMPNNDesignModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="structure"):
            mod.run({}, {}, ctx)


# ── ProteinMPNN Score (mocked adapter) ───────────────────────────────

class TestProteinMPNNScore:
    def test_score_returns_score_collection(self) -> None:
        from modules.proteinmpnn.module_score import ProteinMPNNScoreModule

        with patch(
            "modules.proteinmpnn.module_score.score_sequence",
            return_value=-3.2,
        ):
            mod = ProteinMPNNScoreModule()
            ctx = RunContext("/tmp/test", "n1")
            ps = ProteinStructure(pdb_string=SAMPLE_PDB)
            seq = ProteinSequence(sequence="AG")
            result = mod.run(
                {"structure": ps, "sequence": seq},
                {},
                ctx,
            )

        scores = result["scores"]
        assert isinstance(scores, ScoreCollection)
        assert len(scores.entries) == 1
        assert scores.entries[0].score_id == "proteinmpnn_score"
        assert scores.entries[0].value == -3.2

    def test_missing_structure_raises(self) -> None:
        from modules.proteinmpnn.module_score import ProteinMPNNScoreModule
        mod = ProteinMPNNScoreModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="structure"):
            mod.run({}, {}, ctx)

    def test_missing_sequence_raises(self) -> None:
        from modules.proteinmpnn.module_score import ProteinMPNNScoreModule
        mod = ProteinMPNNScoreModule()
        ctx = RunContext("/tmp/test", "n1")
        ps = ProteinStructure(pdb_string=SAMPLE_PDB)
        with pytest.raises(ValueError, match="sequence"):
            mod.run({"structure": ps}, {}, ctx)


# ── Adapter helper functions ─────────────────────────────────────────

class TestAdapterHelpers:
    def test_get_checkpoint_path_exists(self) -> None:
        from modules.proteinmpnn.adapter import _get_checkpoint_path
        path = _get_checkpoint_path("v_48_020")
        assert path.endswith("v_48_020.pt")

    def test_get_checkpoint_missing_raises(self) -> None:
        from modules.proteinmpnn.adapter import _get_checkpoint_path
        with pytest.raises(FileNotFoundError):
            _get_checkpoint_path("nonexistent_model")

    def test_parse_structure_yields_dict_list(self) -> None:
        from modules.proteinmpnn.adapter import _parse_structure
        result = _parse_structure(SAMPLE_PDB)
        assert isinstance(result, list)
        assert len(result) == 1
        assert "seq" in result[0]
        assert len(result[0]["seq"]) > 0


# ── Constraints Datatype ─────────────────────────────────────────────

class TestConstraintsDatatype:
    def test_default_all_none(self) -> None:
        c = ProteinMPNNConstraints()
        assert c.designable_positions is None
        assert c.fixed_positions is None
        assert c.omit_amino_acids is None

    def test_can_set_fields(self) -> None:
        c = ProteinMPNNConstraints(
            fixed_positions=[1, 2],
            omit_amino_acids=["C"],
            tied_positions=[[1, 5], [3, 7]],
        )
        assert c.fixed_positions == [1, 2]
        assert len(c.tied_positions) == 2


# ── Module Discovery ─────────────────────────────────────────────────

class TestModuleDiscovery:
    def test_38_modules_discoverable(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        ids = {m.module_id for m in mr.list_all()}
        expected_new = {
            "proteinmpnn.design",
            "proteinmpnn.score",
            "proteinmpnn.constraints",
        }
        assert expected_new.issubset(ids)
        assert len(mr) == 44

    def test_constraints_type_registered(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        assert "proteinmpnn.constraints" in tr.list_all()
