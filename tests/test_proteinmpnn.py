"""Tests for ProteinMPNN modules (ticket 07)."""

from typing import Any
from unittest.mock import patch

import pytest

from core.run_context import RunContext
from datatypes import (
    CandidateCollection,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
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

PARSED_TWO_CHAIN_STRUCTURE = [{
    "name": "target",
    "seq": "AGSTW",
    "seq_chain_A": "AG",
    "seq_chain_B": "STW",
}]


class CapturingProteinMPNNProvider:
    def __init__(self, output_sequence: str = "AGSTW") -> None:
        self.output_sequence = output_sequence
        self.request: Any | None = None
        self.inferred = False

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        assert pdb_string == "two-chain-pdb"
        return PARSED_TWO_CHAIN_STRUCTURE

    def design(self, request: Any) -> tuple[list[ProteinSequence], float]:
        self.request = request
        self.inferred = True
        return [ProteinSequence(sequence=self.output_sequence)], -1.0


# ── Constraints Module ───────────────────────────────────────────────

class TestConstraintsModule:
    def test_definitions_publish_the_complete_constraints_contract(self) -> None:
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        constraints_definition = ProteinMPNNConstraintsModule().definition
        constraints_parameters = {
            parameter.name: parameter
            for parameter in constraints_definition.parameters
        }
        assert set(constraints_parameters) == {
            "designable_positions",
            "fixed_positions",
            "designed_chains",
            "fixed_chains",
            "omit_amino_acids",
            "tied_positions",
            "bias_by_res",
        }
        assert all(
            "zero-based target-layout" in constraints_parameters[name].description
            for name in (
                "designable_positions",
                "fixed_positions",
                "tied_positions",
                "bias_by_res",
            )
        )

        design_definition = ProteinMPNNDesignModule().definition
        design_ports = {port.name: port for port in design_definition.input_ports}
        assert design_ports["sequence"].description == (
            "Optional reference sequence aligned exactly to the structure target layout."
        )
        design_parameters = {
            parameter.name: parameter.default
            for parameter in design_definition.parameters
        }
        assert design_parameters["num_sequences"] == 1
        assert design_parameters["temperature"] == 0.1
        assert design_parameters["backbone_noise"] == 0.0

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

    def test_parses_every_public_constraint(self) -> None:
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule

        result = ProteinMPNNConstraintsModule().run(
            {},
            {
                "designable_positions": "[0, 4]",
                "fixed_positions": "[1, 3]",
                "designed_chains": '["A"]',
                "fixed_chains": '["B"]',
                "omit_amino_acids": '["C", "M"]',
                "tied_positions": "[[0, 2, 5], [1, 4]]",
                "bias_by_res": '{"0": {"A": 1.5}, "5": {"G": -0.25}}',
            },
            RunContext("/tmp/test", "n1"),
        )

        assert result["constraints"] == ProteinMPNNConstraints(
            designable_positions=[0, 4],
            fixed_positions=[1, 3],
            designed_chains=["A"],
            fixed_chains=["B"],
            omit_amino_acids=["C", "M"],
            tied_positions=[[0, 2, 5], [1, 4]],
            bias_by_res={0: {"A": 1.5}, 5: {"G": -0.25}},
        )

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

    @pytest.mark.parametrize(
        ("parameters", "message"),
        [
            ({"fixed_positions": "not-json"}, "fixed_positions must be valid JSON"),
            ({"fixed_positions": "[-1]"}, "fixed_positions.*non-negative"),
            ({"designed_chains": '["A", 2]'}, "designed_chains.*strings"),
            ({"omit_amino_acids": '["B"]'}, "omit_amino_acids.*unsupported.*B"),
            ({"tied_positions": "[[0]]"}, "tied_positions.*at least two"),
            ({"bias_by_res": '{"0": {"A": NaN}}'}, "bias_by_res.*finite"),
        ],
    )
    def test_rejects_malformed_constraints(
        self,
        parameters: dict[str, str],
        message: str,
    ) -> None:
        from modules.proteinmpnn.module_constraints import ProteinMPNNConstraintsModule

        with pytest.raises(ValueError, match=message):
            ProteinMPNNConstraintsModule().run(
                {},
                parameters,
                RunContext("/tmp/test", "n1"),
            )


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

    def test_passes_reference_sequence_and_sampling_parameters(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        with patch(
            "modules.proteinmpnn.module_design.design_sequences",
            return_value=([ProteinSequence(sequence="VG")], -2.0),
        ) as mock_design:
            ProteinMPNNDesignModule().run(
                {
                    "structure": ProteinStructure(pdb_string=SAMPLE_PDB),
                    "sequence": ProteinSequence(sequence="VG"),
                },
                {
                    "num_sequences": 1,
                    "temperature": 0.25,
                    "backbone_noise": 0.2,
                },
                RunContext("/tmp/test", "n1", run_id="test-run"),
            )

        assert mock_design.call_args.kwargs["reference_sequence"] == "VG"
        assert mock_design.call_args.kwargs["temperature"] == 0.25
        assert mock_design.call_args.kwargs["backbone_noise"] == 0.2

    @pytest.mark.parametrize(
        ("parameters", "message"),
        [
            ({"model_name": "unknown"}, "model_name"),
            ({"num_sequences": 0}, "num_sequences"),
            ({"temperature": 0.0}, "temperature"),
            ({"backbone_noise": -0.1}, "backbone_noise"),
        ],
    )
    def test_rejects_invalid_sampling_parameters_before_inference(
        self,
        parameters: dict[str, object],
        message: str,
    ) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        with patch(
            "modules.proteinmpnn.module_design.design_sequences",
        ) as mock_design:
            with pytest.raises(ValueError, match=message):
                ProteinMPNNDesignModule().run(
                    {"structure": ProteinStructure(pdb_string=SAMPLE_PDB)},
                    parameters,
                    RunContext("/tmp/test", "n1", run_id="test-run"),
                )
        mock_design.assert_not_called()

    def test_missing_structure_raises(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
        mod = ProteinMPNNDesignModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="structure"):
            mod.run({}, {}, ctx)

    def test_adapter_converts_first_and_last_target_positions_once(self) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider()
        design_sequences(
            pdb_string="two-chain-pdb",
            constraints=ProteinMPNNConstraints(fixed_positions=[0, 4]),
            provider=provider,
        )

        assert provider.request is not None
        assert provider.request.num_sequences == 1
        assert provider.request.temperature == 0.1
        assert provider.request.backbone_noise == 0.0
        assert provider.request.fixed_position_dict == {
            "target": {"A": [1], "B": [3]}
        }

    def test_adapter_translates_multichain_ties_omits_and_residue_biases(
        self,
    ) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider()
        design_sequences(
            pdb_string="two-chain-pdb",
            constraints=ProteinMPNNConstraints(
                designed_chains=["A", "B"],
                fixed_chains=[],
                omit_amino_acids=["C", "M"],
                tied_positions=[[0, 4], [1, 2]],
                bias_by_res={0: {"A": 1.5}, 4: {"G": -0.25}},
            ),
            provider=provider,
        )

        request = provider.request
        assert request is not None
        assert request.chain_dict == {"target": (["A", "B"], [])}
        assert request.omit_amino_acids == ["C", "M"]
        assert request.tied_positions_dict == {
            "target": [
                {"A": [1], "B": [3]},
                {"A": [2], "B": [1]},
            ]
        }
        assert set(request.bias_by_res_dict["target"]) == {"A", "B"}
        assert len(request.bias_by_res_dict["target"]["A"]) == 2
        assert len(request.bias_by_res_dict["target"]["B"]) == 3
        assert request.bias_by_res_dict["target"]["A"][0][0] == 1.5
        assert request.bias_by_res_dict["target"]["B"][2][5] == -0.25

    def test_adapter_translates_designable_positions_to_fixed_complement(
        self,
    ) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider()
        design_sequences(
            pdb_string="two-chain-pdb",
            constraints=ProteinMPNNConstraints(designable_positions=[0, 4]),
            provider=provider,
        )

        assert provider.request is not None
        assert provider.request.fixed_position_dict == {
            "target": {"A": [2], "B": [1, 2]}
        }

    def test_adapter_translates_designed_and_fixed_chains(self) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider(output_sequence="STW")
        design_sequences(
            pdb_string="two-chain-pdb",
            constraints=ProteinMPNNConstraints(
                designed_chains=["B"],
                fixed_chains=["A"],
            ),
            provider=provider,
        )

        assert provider.request is not None
        assert provider.request.chain_dict == {"target": (["B"], ["A"])}

    def test_adapter_honors_reference_sequence_port_by_chain(self) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider(output_sequence="VCDEA")
        design_sequences(
            pdb_string="two-chain-pdb",
            reference_sequence="VCDEA",
            provider=provider,
        )

        assert provider.request is not None
        assert provider.request.reference_sequences == {"A": "VC", "B": "DEA"}

    @pytest.mark.parametrize("reference_sequence", ["VCDE", "VCDEAA"])
    def test_adapter_rejects_reference_sequence_length_mismatch_before_inference(
        self,
        reference_sequence: str,
    ) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider()
        with pytest.raises(
            ValueError,
            match="does not match structure length 5; padding and truncation",
        ):
            design_sequences(
                pdb_string="two-chain-pdb",
                reference_sequence=reference_sequence,
                provider=provider,
            )
        assert provider.inferred is False

    @pytest.mark.parametrize(
        ("constraints", "message"),
        [
            (
                ProteinMPNNConstraints(fixed_positions=[-1]),
                "position -1 must be a non-negative zero-based",
            ),
            (
                ProteinMPNNConstraints(fixed_positions=[5]),
                "position 5 is outside target layout of length 5",
            ),
            (
                ProteinMPNNConstraints(designed_chains=["Z"]),
                "chain IDs are not present.*Z",
            ),
            (
                ProteinMPNNConstraints(
                    designed_chains=["A"],
                    fixed_chains=["A"],
                ),
                "both designed and fixed.*A",
            ),
            (
                ProteinMPNNConstraints(tied_positions=[[0]]),
                "tied position group.*at least two",
            ),
            (
                ProteinMPNNConstraints(omit_amino_acids=["B"]),
                "unsupported amino acids in omit_amino_acids.*B",
            ),
            (
                ProteinMPNNConstraints(bias_by_res={0: {"B": 1.0}}),
                "unsupported amino acid 'B' in bias_by_res",
            ),
            (
                ProteinMPNNConstraints(
                    fixed_positions=[0],
                    designed_chains=["B"],
                    fixed_chains=["A"],
                ),
                "fixed position 0 belongs to already-fixed chain A",
            ),
            (
                ProteinMPNNConstraints(
                    bias_by_res={0: {"A": 1.0}},
                    designed_chains=["B"],
                    fixed_chains=["A"],
                ),
                "bias_by_res position 0 belongs to fixed chain A",
            ),
            (
                ProteinMPNNConstraints(
                    tied_positions=[[0, 1]],
                    designed_chains=["B"],
                    fixed_chains=["A"],
                ),
                "tied position group 0 contains no designable chain",
            ),
            (
                ProteinMPNNConstraints(
                    fixed_positions=[0],
                    tied_positions=[[0, 1]],
                ),
                "tied position group 0 includes fixed position A:1",
            ),
            (
                ProteinMPNNConstraints(
                    designed_chains=["B"],
                    fixed_chains=["A"],
                    tied_positions=[[0, 2]],
                ),
                "tied position group 0 includes fixed-chain position A:1",
            ),
            (
                ProteinMPNNConstraints(
                    designable_positions=[0],
                    bias_by_res={1: {"A": 1.0}},
                ),
                "bias_by_res position 1 is fixed by the effective position mask",
            ),
        ],
    )
    def test_adapter_rejects_invalid_constraints_before_inference(
        self,
        constraints: ProteinMPNNConstraints,
        message: str,
    ) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider()
        with pytest.raises(ValueError, match=message):
            design_sequences(
                pdb_string="two-chain-pdb",
                constraints=constraints,
                provider=provider,
            )
        assert provider.inferred is False


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
        assert len(mr) == 45

    def test_constraints_type_registered(self) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules
        tr = TypeRegistry()
        mr = ModuleRegistry(tr)
        discover_modules(mr)
        assert "proteinmpnn.constraints" in tr.list_all()
