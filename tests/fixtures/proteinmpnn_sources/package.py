"""Independent structure-Candidate source for ProteinMPNN acceptance."""

from __future__ import annotations

from typing import Any

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import (
    OperationCall,
    OperationContext,
    ReadinessResult,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


_VERSION = "3.0.0"
_SOURCE_NODE_BINDING_VERSION = "5.0.0"
_SEQUENCE_SOURCE_NODE_BINDING_VERSION = "4.0.0"
_CANDIDATEIZE_NODE_BINDING_VERSION = "2.0.0"


def _fixture_structure(parent_index: int) -> ProteinStructure:
    residues = (
        ("A", 1, "ALA"),
        ("A", 2, "GLY"),
        ("B", 1, "SER"),
        ("B", 2, "THR"),
        ("B", 3, "TRP"),
    )
    lines = [f"REMARK fixture-parent-{parent_index}"]
    for serial, (chain_id, position, residue_name) in enumerate(
        residues,
        start=1,
    ):
        coordinate = float(serial)
        lines.append(
            f"ATOM  {serial:5d} {'CA':^4s} "
            f"{residue_name:>3s} {chain_id}{position:4d}    "
            f"{coordinate:8.3f}{0.0:8.3f}{0.0:8.3f}"
            f"  1.00 20.00{'':10}{'C':>2s}  "
        )
        if serial == 2:
            lines.append("TER")
    return ProteinStructure("\n".join([*lines, "TER", "END", ""]))


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
                    _fixture_structure(index),
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
        parents = inputs["structure_candidates"].value
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


class _StructureCandidateize:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if (
            set(call.inputs) != {"structure"}
            or call.node_parameters
            or call.binding_parameters
            or type(call.inputs["structure"].value) is not ProteinStructure
        ):
            raise ValueError(
                "ProteinMPNN structure candidate fixture requires one structure"
            )
        with self._run_resources.engine_invocation():
            candidate = Candidate(
                "fixture-candidateized-structure",
                call.inputs["structure"].value,
                (),
                {"fixture_role": "candidateized_structure"},
            )
        return {
            "structure_candidates": CandidateCollection(
                "fixture-candidateized-structure-collection",
                "protein.structure",
                (candidate,),
            )
        }


def _build(operation: str):
    def factory(context: OperationContext) -> object:
        implementation = {
            "source": _Source,
            "sequence_source": _SequenceSource,
            "candidateize": _StructureCandidateize,
        }[operation]
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
        DefinitionResource("candidateize_structure.yaml"),
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
            method_id="contract_test.proteinmpnn_candidateize.method",
            version="1.0.0",
            algorithm_identity={"name": "exact-single-candidate-wrapper"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "identity"},
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
            version=_SOURCE_NODE_BINDING_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.proteinmpnn_source",
                _SOURCE_NODE_BINDING_VERSION,
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
                    _SOURCE_NODE_BINDING_VERSION,
                    {},
                ),
                build=_build("source"),
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_source/availability",
                    _SOURCE_NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_source/readiness",
                    _SOURCE_NODE_BINDING_VERSION,
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
            binding_id=(
                "contract_test.proteinmpnn_structure_candidateize.direct"
            ),
            version=_CANDIDATEIZE_NODE_BINDING_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.proteinmpnn_structure_candidateize",
                _CANDIDATEIZE_NODE_BINDING_VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.proteinmpnn_candidateize.method",
                "1.0.0",
            ),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_structure_candidateize/factory",
                    _CANDIDATEIZE_NODE_BINDING_VERSION,
                    {},
                ),
                build=_build("candidateize"),
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_structure_candidateize/availability",
                    _CANDIDATEIZE_NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_structure_candidateize/readiness",
                    _CANDIDATEIZE_NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": (
                    "contract_test.proteinmpnn_structure_candidateize.direct"
                ),
                "source": "contract-test-fixture",
            },
        ),
        ExecutionBindingDefinition(
            binding_id="contract_test.proteinmpnn_sequence_source.direct",
            version=_SEQUENCE_SOURCE_NODE_BINDING_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.proteinmpnn_sequence_source",
                _SEQUENCE_SOURCE_NODE_BINDING_VERSION,
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
                    _SEQUENCE_SOURCE_NODE_BINDING_VERSION,
                    {},
                ),
                build=_build("sequence_source"),
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_sequence_source/availability",
                    _SEQUENCE_SOURCE_NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.proteinmpnn_sequence_source/readiness",
                    _SEQUENCE_SOURCE_NODE_BINDING_VERSION,
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
