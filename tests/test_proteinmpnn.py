"""Tests for ProteinMPNN modules (ticket 07)."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
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
        self.requests: list[Any] = []
        self.parsed_pdb_strings: list[str] = []
        self.inferred = False
        self.provider_identity = "capturing-proteinmpnn"

    def parse_structure(self, pdb_string: str) -> list[dict[str, Any]]:
        self.parsed_pdb_strings.append(pdb_string)
        return PARSED_TWO_CHAIN_STRUCTURE

    def design(
        self,
        request: Any,
    ) -> tuple[list[ProteinSequence], list[float]]:
        self.request = request
        self.requests.append(request)
        self.inferred = True
        return (
            [
                ProteinSequence(
                    sequence=self.output_sequence[:-1]
                    + "ACDEFGHIKLMNPQRSTVWY"[sample_index % 20]
                )
                for sample_index in range(request.num_sequences)
            ],
            [
                -float(sample_index + 1)
                for sample_index in range(request.num_sequences)
            ],
        )


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
                "bias_by_res": '{"6": {"A": 1.5}, "7": {"G": -0.25}}',
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
            bias_by_res={6: {"A": 1.5}, 7: {"G": -0.25}},
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
    def test_definition_declares_exactly_one_structure_input_mode(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        definition = ProteinMPNNDesignModule().definition
        ports = {port.name: port for port in definition.input_ports}
        assert ports["structure"].type_id == "protein.structure"
        assert ports["structure"].required is False
        assert ports["structures"].type_id == "candidate.collection"
        assert ports["structures"].required is False
        assert [
            (group.name, group.alternatives, group.allow_multiple)
            for group in definition.input_groups
        ] == [
            (
                "design_input",
                (("structure",), ("structures",)),
                False,
            )
        ]

    @pytest.mark.parametrize(
        "inputs",
        [
            {},
            {
                "structure": ProteinStructure(pdb_string=SAMPLE_PDB),
                "structures": CandidateCollection(
                    collection_id="parents",
                    item_type="protein.structure",
                    items=[],
                ),
            },
        ],
    )
    def test_requires_exactly_one_structure_input(self, inputs: dict[str, Any]) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        with pytest.raises(ValueError, match="exactly one"):
            ProteinMPNNDesignModule().run(
                inputs,
                {},
                RunContext("/tmp/test", "n1", run_id="test-run"),
            )

    def test_collection_design_produces_five_scored_children_per_actual_parent(
        self,
    ) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        parents = CandidateCollection(
            collection_id="selected-parents",
            item_type="protein.structure",
            items=[
                Candidate(
                    candidate_id=f"parent-{parent_index}",
                    data=ProteinStructure(
                        pdb_string=f"parent-pdb-{parent_index}"
                    ),
                )
                for parent_index in range(3)
            ],
        )
        provider = CapturingProteinMPNNProvider()

        result = ProteinMPNNDesignModule(provider=provider).run(
            {"structures": parents},
            {
                "model_name": "v_48_010",
                "num_sequences": 5,
                "temperature": 0.25,
                "backbone_noise": 0.2,
            },
            RunContext("/tmp/test", "mpnn-node", run_id="run-15", seed=77),
        )

        candidates = result["candidates"]
        scores = result["scores"]
        assert len(candidates) == 15
        assert len(scores) == 15
        assert provider.parsed_pdb_strings == [
            "parent-pdb-0",
            "parent-pdb-1",
            "parent-pdb-2",
        ]
        assert [request.num_sequences for request in provider.requests] == [5, 5, 5]
        assert [request.seed for request in provider.requests] == [77, 77, 77]

        score_by_subject = {
            entry.subjects[0]: entry.value
            for entry in scores
        }
        for parent_index in range(3):
            children = [
                child
                for child in candidates
                if child.parent_ids == [f"parent-{parent_index}"]
            ]
            assert [child.metadata["sample_index"] for child in children] == list(
                range(5)
            )
            assert [score_by_subject[child.candidate_id] for child in children] == [
                -1.0,
                -2.0,
                -3.0,
                -4.0,
                -5.0,
            ]
            assert {
                child.metadata["effective_seed"]
                for child in children
            } == {77}
            assert {
                child.metadata["provider"]
                for child in children
            } == {"capturing-proteinmpnn"}
            assert {child.metadata["model"] for child in children} == {"v_48_010"}
            assert {
                (
                    child.metadata["temperature"],
                    child.metadata["backbone_noise"],
                )
                for child in children
            } == {(0.25, 0.2)}
            assert all(
                child.metadata["constraint_identity"].startswith("sha256:")
                for child in children
            )

    def test_explicit_node_seed_overrides_run_seed(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        provider = CapturingProteinMPNNProvider()
        result = ProteinMPNNDesignModule(provider=provider).run(
            {"structure": ProteinStructure(pdb_string="two-chain-pdb")},
            {"seed": 123},
            RunContext("/tmp/test", "mpnn-node", run_id="seed-run", seed=77),
        )

        assert provider.requests[0].seed == 123
        assert result["candidates"].items[0].metadata["effective_seed"] == 123

    def test_explicit_node_seed_is_the_public_cache_identity(
        self,
        tmp_path: Path,
    ) -> None:
        from core.executor import Executor
        from core.graph import Workflow, WorkflowEdge, WorkflowNode
        from core.module_definition import ModuleDefinition
        from core.run_manifest import read_run_manifest
        from core.workflow_module import WorkflowModule
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        class StructureSourceModule(WorkflowModule):
            @property
            def definition(self) -> ModuleDefinition:
                return ModuleDefinition.from_yaml_string(
                    """
module_id: test.structure_source
version: 1.0.0
display_name: Structure Source
category: input
output_ports:
  - name: structure
    type_id: protein.structure
"""
                )

            def run(
                self,
                inputs: dict[str, Any],
                parameters: dict[str, Any],
                context: RunContext,
            ) -> dict[str, Any]:
                return {
                    "structure": ProteinStructure(pdb_string="two-chain-pdb")
                }

        def workflow() -> Workflow:
            result = Workflow()
            result.add_node(WorkflowNode(
                node_id="source",
                module_id="test.structure_source",
                module_version="1.0.0",
            ))
            result.add_node(WorkflowNode(
                node_id="design",
                module_id="proteinmpnn.design",
                module_version="1.2.0",
                parameters={"seed": 123},
            ))
            result.add_edge(WorkflowEdge(
                source_node_id="source",
                source_port="structure",
                target_node_id="design",
                target_port="structure",
            ))
            return result

        first_provider = CapturingProteinMPNNProvider()
        asyncio.run(Executor().execute(
            workflow(),
            {
                "test.structure_source": StructureSourceModule(),
                "proteinmpnn.design": ProteinMPNNDesignModule(
                    provider=first_provider
                ),
            },
            str(tmp_path),
            "first-run",
            seed=11,
        ))
        first_manifest = read_run_manifest(
            tmp_path / "runs" / "first-run"
        )
        second_provider = CapturingProteinMPNNProvider()
        second_outputs = asyncio.run(Executor().execute(
            workflow(),
            {
                "test.structure_source": StructureSourceModule(),
                "proteinmpnn.design": ProteinMPNNDesignModule(
                    provider=second_provider
                ),
            },
            str(tmp_path),
            "second-run",
            seed=22,
        ))

        assert len(first_provider.requests) == 1
        assert first_manifest["effective_seeds"] == {"design": 123}
        assert first_manifest["providers"]["calls"] == [
            {
                "provider": "capturing-proteinmpnn",
                "operation": "design_sequences",
                "model": "v_48_020",
                "details": {
                    "node_id": "design",
                    "parent_candidate_id": "design",
                    "candidate_ids": ["mpnn-first-run-0-0"],
                    "effective_seed": 123,
                },
            }
        ]
        assert second_provider.requests == []
        assert (
            second_outputs["design"]["candidates"].items[0]
            .metadata["effective_seed"]
            == 123
        )

    @pytest.mark.parametrize(
        ("sequences", "scores", "message"),
        [
            ([], [], "returned 0 sequences; expected 1"),
            (
                [ProteinSequence(sequence="AGSTW")],
                [],
                "incomplete per-sequence scores",
            ),
            (
                [ProteinSequence(sequence="AG")],
                [-1.0],
                "sequence length 2 does not match target length 5",
            ),
        ],
    )
    def test_incomplete_provider_output_fails_the_node_contract(
        self,
        sequences: list[ProteinSequence],
        scores: list[float],
        message: str,
    ) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        class IncompleteProvider(CapturingProteinMPNNProvider):
            def design(
                self,
                request: Any,
            ) -> tuple[list[ProteinSequence], list[float]]:
                self.requests.append(request)
                return sequences, scores

        with pytest.raises(RuntimeError, match=message):
            ProteinMPNNDesignModule(provider=IncompleteProvider()).run(
                {"structure": ProteinStructure(pdb_string="two-chain-pdb")},
                {},
                RunContext("/tmp/test", "mpnn-node", run_id="incomplete"),
            )

    def test_provider_scoring_failure_fails_the_node(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        class ScoringFailureProvider(CapturingProteinMPNNProvider):
            def design(
                self,
                request: Any,
            ) -> tuple[list[ProteinSequence], list[float]]:
                raise RuntimeError("ProteinMPNN score computation failed")

        with pytest.raises(RuntimeError, match="score computation failed"):
            ProteinMPNNDesignModule(provider=ScoringFailureProvider()).run(
                {"structure": ProteinStructure(pdb_string="two-chain-pdb")},
                {},
                RunContext("/tmp/test", "mpnn-node", run_id="score-failure"),
            )

    def test_design_produces_candidates(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        mock_seq = ProteinSequence(sequence="AGSWFC")
        with patch(
            "modules.proteinmpnn.module_design.design_sequences",
            return_value=([mock_seq, mock_seq], [-1.5, -1.25]),
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
        assert len(scores.entries) == 2
        assert scores.entries[0].score_id == "proteinmpnn_score"
        assert [score.subjects for score in scores] == [
            [candidates.items[0].candidate_id],
            [candidates.items[1].candidate_id],
        ]

    def test_passes_constraints(self) -> None:
        from modules.proteinmpnn.module_design import ProteinMPNNDesignModule

        mock_seq = ProteinSequence(sequence="AAAA")
        constraints = ProteinMPNNConstraints(fixed_positions=[1, 2, 3])

        with patch(
            "modules.proteinmpnn.module_design.design_sequences",
            return_value=([mock_seq], [-2.0]),
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
            return_value=([ProteinSequence(sequence="VG")], [-2.0]),
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

    def test_adapter_translates_multichain_ties_and_omits(
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

    def test_adapter_translates_multichain_residue_biases(self) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider()
        design_sequences(
            pdb_string="two-chain-pdb",
            constraints=ProteinMPNNConstraints(
                bias_by_res={0: {"A": 1.5}, 4: {"G": -0.25}},
            ),
            provider=provider,
        )

        request = provider.request
        assert request is not None
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

        provider = CapturingProteinMPNNProvider(output_sequence="AGSTW")
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
                "fixed_positions.*non-negative zero-based",
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
                "tied_positions group.*at least two",
            ),
            (
                ProteinMPNNConstraints(omit_amino_acids=["B"]),
                "omit_amino_acids.*unsupported amino acids.*B",
            ),
            (
                ProteinMPNNConstraints(bias_by_res={0: {"B": 1.0}}),
                "bias_by_res.*unsupported amino acid 'B'",
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
            (
                ProteinMPNNConstraints(
                    tied_positions=[[0, 4]],
                    bias_by_res={0: {"A": 1.0}},
                ),
                "bias_by_res position 0 belongs to tied position group 0",
            ),
            (
                ProteinMPNNConstraints(
                    omit_amino_acids=list("ACDEFGHIKLMNPQRSTVWYX"),
                ),
                "omit_amino_acids must leave at least one",
            ),
            (
                ProteinMPNNConstraints(
                    omit_amino_acids=["A"],
                    bias_by_res={0: {"A": 1.0}},
                ),
                "bias_by_res position 0 targets globally omitted amino acid A",
            ),
            (
                ProteinMPNNConstraints(
                    bias_by_res={0: {"A": True}},
                ),
                "bias_by_res bias for 0/A must be numeric",
            ),
            (
                ProteinMPNNConstraints(
                    designed_chains=[1],
                ),
                "designed_chains entries must be non-empty strings",
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

    def test_adapter_rejects_falsy_malformed_constraints_before_inference(
        self,
    ) -> None:
        from modules.proteinmpnn.adapter import design_sequences

        provider = CapturingProteinMPNNProvider()
        with pytest.raises(
            ValueError, match="constraints must be ProteinMPNNConstraints"
        ):
            design_sequences(
                pdb_string="two-chain-pdb",
                constraints={},  # type: ignore[arg-type]
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
