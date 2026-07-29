"""Independent Candidate source for protein I/O public-seam tests."""

from __future__ import annotations

from typing import Any, Mapping

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    LazyImplementationFactory,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
)


class _StructureSource:
    def __init__(self, resources: Any) -> None:
        self._resources = resources

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or node_parameters or binding_parameters:
            raise ValueError("structure source accepts no values")
        with self._resources.engine_invocation(
            engine_identity="contract_test.structure_candidates.method/2.0.0",
        ):
            candidates = [
                Candidate(
                    candidate_id=f"fixture-structure-{index:02d}",
                    data=ProteinStructure(
                        pdb_string=(
                            f"REMARK provider-native-{index:02d}\n"
                            f"MODEL     {index + 1:4d}\n"
                            "ATOM      1  CA  GLY A   1      "
                            f"{index + 1:5d}.000   2.000   3.000  "
                            "1.00 20.00           C\n"
                            "ENDMDL\nEND\n"
                        ),
                        source=f"provider-{index:02d}",
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

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if inputs or node_parameters or binding_parameters:
            raise ValueError("scalar source accepts no values")
        with self._resources.engine_invocation(
            engine_identity=f"contract_test.{self._kind}.method/2.0.0",
        ):
            if self._kind == "protein_sequence":
                return {"sequence": ProteinSequence(sequence="ACDEFG")}
            return {
                "structure": ProteinStructure(
                    pdb_string=(
                        "REMARK contract-test-provider-native\n"
                        "ATOM      1  CA  GLY A   1      "
                        "1.000   2.000   3.000  1.00 20.00           C\n"
                        "END\n"
                    ),
                    source="contract-test-provider",
                )
            }


def _build(kind: str):
    def factory(**kwargs: object) -> object:
        if kind == "structure_candidates":
            return _StructureSource(kwargs["run_resources"])
        return _ScalarSource(kwargs["run_resources"], kind)

    return factory


def _method(kind: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"contract_test.{kind}.method",
        version="2.0.0",
        algorithm_identity={"name": "deterministic-fixture"},
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "provider-native"},
        source_identity={"kind": "contract-test-fixture"},
        scale_contract={"kind": "identity"},
    )


def _binding(kind: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"contract_test.{kind}.direct",
        version="2.0.0",
        node_type=ContractIdentity(
            "node_type",
            f"contract_test.{kind}",
            "2.0.0",
        ),
        method=ContractIdentity(
            "method",
            f"contract_test.{kind}.method",
            "2.0.0",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"contract_test.{kind}/factory",
                "2.0.0",
                {},
            ),
            build=_build(kind),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"contract_test.{kind}/availability",
                "2.0.0",
                {},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"contract_test.{kind}/readiness",
                "2.0.0",
                {},
            ),
            prerequisites={},
            check=lambda environment: True,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"contract_test.{kind}.direct",
            "source": "contract-test-fixture",
        },
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.0.0",
    package_id="contract_test.protein_io_sources",
    package_version="2.0.0",
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
