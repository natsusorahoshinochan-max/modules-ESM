"""Independent Candidate source for protein I/O public-seam tests."""

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


class _StructureSource:
    def __init__(self, resources: Any) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or node_parameters or binding_parameters:
            raise ValueError("structure source accepts no values")
        with self._resources.engine_invocation():
            candidates = [
                Candidate(
                    candidate_id=f"fixture-structure-{index:02d}",
                    data=ProteinStructure(
                        pdb_string=(
                            f"REMARK provider-native-{index:02d}\n"
                            f"MODEL     {index + 1:4d}\n"
                            "ATOM      1  CA  GLY A   1    "
                            f"{float(index + 1):8.3f}"
                            f"{2.0:8.3f}{3.0:8.3f}"
                            f"{1.0:6.2f}{20.0:6.2f}           C  \n"
                            "ENDMDL\nEND\n"
                        ),
                    ),
                    parent_ids=[],
                    metadata={"sample_slot": index},
                )
                for index in range(15)
            ]
        return {
            "structures": CandidateCollection(
                collection_id="fixture-structures",
                item_type="protein.structure",
                items=candidates,
            )
        }


class _ScalarSource:
    def __init__(self, resources: Any, kind: str) -> None:
        self._resources = resources
        self._kind = kind

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or node_parameters or binding_parameters:
            raise ValueError("scalar source accepts no values")
        with self._resources.engine_invocation():
            if self._kind == "protein_sequence":
                return {"sequence": ProteinSequence(sequence="ACDEFG")}
            return {
                "structure": ProteinStructure(
                    pdb_string=(
                        "REMARK contract-test-provider-native\n"
                        "ATOM      1  CA  GLY A   1       "
                        "1.000   2.000   3.000  1.00 20.00           C  \n"
                        "END\n"
                    ),
                )
            }


def _build(kind: str):
    def factory(context: OperationContext) -> object:
        if kind == "structure_candidates":
            return _StructureSource(context.resources)
        return _ScalarSource(context.resources, kind)

    return factory


def _method(kind: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"contract_test.{kind}.method",
        algorithm_identity={"name": "deterministic-fixture"},
        model_identity={"kind": "none"},
        featurization_identity={"kind": "provider-native"},
        scale_contract={"kind": "identity"},
    )


def _binding(kind: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"contract_test.{kind}.direct",
        node_type=ContractIdentity(
            "node_type",
            f"contract_test.{kind}"),
        method=ContractIdentity(
            "method",
            f"contract_test.{kind}.method"),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"contract_test.{kind}/factory",
                {},
            ),
            build=_build(kind),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"contract_test.{kind}/availability",
                {},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"contract_test.{kind}/readiness",
                {},
            ),
            prerequisites={},
            check=lambda environment: ReadinessResult(True),
        ),
        deterministic=True,
        cacheable=True)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="contract_test.protein_io_sources",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definition.yaml"),
        DefinitionResource("sequence.yaml"),
        DefinitionResource("structure.yaml"),
    ),
    methods=tuple(
        _method(kind)
        for kind in (
            "structure_candidates",
            "protein_sequence",
            "protein_structure",
        )
    ),
    bindings=tuple(
        _binding(kind)
        for kind in (
            "structure_candidates",
            "protein_sequence",
            "protein_structure",
        )
    ),
)
