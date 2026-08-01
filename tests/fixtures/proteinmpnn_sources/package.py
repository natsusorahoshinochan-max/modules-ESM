"""Independent structure-Candidate source for ProteinMPNN acceptance."""

from __future__ import annotations

from typing import Any

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    OperationCall,
    OperationContext,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
)


_VERSION = "2.1.0"


class _Source:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            inputs
            or set(node_parameters) != {"parent_count"}
            or binding_parameters
        ):
            raise ValueError(
                "ProteinMPNN source accepts only exact parent_count"
            )
        count = node_parameters["parent_count"]
        if type(count) is not int or not 1 <= count <= 10:
            raise ValueError("ProteinMPNN parent_count is invalid")
        with self._run_resources.engine_invocation():
            parents = [
                Candidate(
                    f"fixture-parent-{index}",
                    ProteinStructure(
                        (
                            f"REMARK fixture-parent-{index}\n"
                            "ATOM      1  CA  ALA A   1       "
                            "0.000   0.000   0.000  1.00 20.00           C\n"
                            "END\n"
                        ),
                    ),
                    [],
                    {"fixture_parent_index": index},
                )
                for index in range(count)
            ]
        return {
            "structure_candidates": CandidateCollection(
                "fixture-proteinmpnn-parents",
                "protein.structure",
                parents,
            ),
            "sequence": ProteinSequence(
                "AGSTW",
                ["A:1", "A:2", "B:1", "B:2", "B:3"],
            ),
        }


class _SequenceSource:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if (
            set(inputs) != {"structure_candidates"}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "ProteinMPNN sequence source requires exact parents"
            )
        parents = inputs["structure_candidates"]
        if (
            type(parents) is not CandidateCollection
            or parents.item_type != "protein.structure"
            or not parents.items
        ):
            raise ValueError("ProteinMPNN sequence parents are invalid")
        with self._run_resources.engine_invocation():
            sequences = [
                Candidate(
                    f"fixture-sequence-{index}",
                    ProteinSequence(
                        "AGSTW",
                        ["A:1", "A:2", "B:1", "B:2", "B:3"],
                    ),
                    [parent.candidate_id],
                    {"fixture_parent_index": index},
                )
                for index, parent in enumerate(parents.items)
            ]
        return {
            "sequence_candidates": CandidateCollection(
                "fixture-proteinmpnn-sequences",
                "protein.sequence",
                sequences,
            )
        }


def _build(operation: str):
    def factory(context: OperationContext) -> object:
        implementation = (
            _Source
            if operation == "source"
            else _SequenceSource
        )
        return implementation(context.resources)

    return factory


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.proteinmpnn_sources",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definition.yaml"),
        DefinitionResource("sequence_source.yaml"),
    ),
    methods=(
        MethodDefinition(
            method_id="contract_test.proteinmpnn_source.method",
            version=_VERSION,
            algorithm_identity={"name": "independent-literal-source"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "literal"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "identity"},
        ),
        MethodDefinition(
            method_id="contract_test.proteinmpnn_sequence_source.method",
            version=_VERSION,
            algorithm_identity={"name": "independent-literal-sequence-source"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "literal"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "identity"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.proteinmpnn_source.direct",
            version=_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.proteinmpnn_source",
                _VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.proteinmpnn_source.method",
                _VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_source/factory",
                    _VERSION,
                    {},
                ),
                build=_build("source"),
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_source/availability",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_source/readiness",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "contract_test.proteinmpnn_source.direct",
                "source": "contract-test-fixture",
            },
        ),
        ExecutionBindingDefinition(
            binding_id="contract_test.proteinmpnn_sequence_source.direct",
            version=_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.proteinmpnn_sequence_source",
                _VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.proteinmpnn_sequence_source.method",
                _VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_sequence_source/factory",
                    _VERSION,
                    {},
                ),
                build=_build("sequence_source"),
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_sequence_source/availability",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_sequence_source/readiness",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": (
                    "contract_test.proteinmpnn_sequence_source.direct"
                ),
                "source": "contract-test-fixture",
            },
        ),
    ),
)
