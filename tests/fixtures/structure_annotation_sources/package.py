"""Independent source registration for structure-annotation acceptance."""

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
    CandidateDataReference,
)
from datatypes.prompt import ProteinPrompt
from datatypes.residue import (
    ResidueLayout,
    ResidueTrack,
)
from datatypes.structure import ProteinStructure
from modules.structure_annotation.domain import (
    DSSPAnnotation,
    StructureAnnotationTrack,
)


_VERSION = "4.0.0"
_OPERATIONS = ("candidate_source", "value_source")


def _structure() -> ProteinStructure:
    return ProteinStructure(
        pdb_string=(
            "ATOM      1  CA  GLY A   1       "
            "1.000   2.000   3.000  1.00 20.00           C  \n"
            "ATOM      2  CA  ALA A   2       "
            "2.000   3.000   4.000  1.00 20.00           C  \n"
            "TER\nEND\n"
        ),
    )


class _CandidateSource:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.inputs or call.node_parameters or call.binding_parameters:
            raise ValueError(
                "structure annotation Candidate source accepts no values"
            )
        structure = _structure()
        with self._run_resources.engine_invocation():
            subjects = CandidateCollection(
                collection_id="fixture-structure-subjects",
                item_type="protein.structure",
                items=[
                    Candidate(
                        candidate_id="fixture-structure-subject",
                        data=structure,
                    )
                ],
            )
            references = CandidateCollection(
                collection_id="fixture-structure-references",
                item_type="protein.structure",
                items=[
                    Candidate(
                        candidate_id="fixture-structure-reference",
                        data=structure,
                    )
                ],
            )
        return {"subjects": subjects, "references": references}


def _admitted_reference(
    call: OperationCall,
    port_name: str,
) -> CandidateDataReference:
    collection = call.inputs[port_name].value
    if type(collection) is not CandidateCollection or len(collection.items) != 1:
        raise ValueError(f"{port_name} must contain exactly one Candidate")
    references = call.inputs[port_name].candidate_data
    if len(references) != 1:
        raise ValueError(f"{port_name} must have one admitted reference")
    reference = references[0]
    if reference.candidate_id != collection.items[0].candidate_id:
        raise ValueError(f"{port_name} reference must name its Candidate")
    return reference


class _ValueSource:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError(
                "structure annotation value source accepts no parameters"
            )
        if set(call.inputs) != {"subjects", "references"}:
            raise ValueError(
                "structure annotation values require subjects and references"
            )
        subject = _admitted_reference(call, "subjects")
        reference = _admitted_reference(call, "references")
        layout = ResidueLayout(
            chain_id="A",
            length=2,
            residue_ids=["A:1", "A:2"],
        )
        with self._run_resources.engine_invocation():
            annotations = DSSPAnnotation(
                subject=subject,
                layout=layout,
                secondary_structure=("H", "C"),
                sasa=(10.0, 20.0),
            )
            expected = StructureAnnotationTrack(
                subject=reference,
                layout=layout,
                values=("H", "E"),
            )
            observed = StructureAnnotationTrack(
                subject=subject,
                layout=layout,
                values=("G", "E"),
            )
            sasa_track = StructureAnnotationTrack(
                subject=subject,
                layout=layout,
                values=(10.0, None),
            )
            protein_prompt = ProteinPrompt(
                target_layout=layout,
                sequence_track=ResidueTrack(["G", "A"], None),
                secondary_structure_track=ResidueTrack(["H", None], None),
                sasa_track=ResidueTrack([None, None], None),
            )
        return {
            "annotations": annotations,
            "expected": expected,
            "observed": observed,
            "sasa_track": sasa_track,
            "protein_prompt": protein_prompt,
        }


def _build(operation: str):
    implementation = (
        _CandidateSource if operation == "candidate_source" else _ValueSource
    )

    def build(context: OperationContext) -> object:
        return implementation(context.resources)

    return build


def _binding(operation: str) -> ExecutionBindingDefinition:
    contract_id = f"contract_test.structure_annotation_{operation}"
    return ExecutionBindingDefinition(
        binding_id=f"{contract_id}.direct",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            contract_id,
            _VERSION,
        ),
        method=ContractIdentity(
            "method",
            f"{contract_id}.method",
            _VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"{contract_id}/factory",
                _VERSION,
                {},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"{contract_id}/availability",
                _VERSION,
                {},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"{contract_id}/readiness",
                _VERSION,
                {},
            ),
            prerequisites={},
            check=lambda environment: ReadinessResult(True),
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"{contract_id}.direct",
            "source": "contract-test-fixture",
        },
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.structure_annotation_sources",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("candidate_source.yaml"),
        DefinitionResource("value_source.yaml"),
    ),
    methods=tuple(
        MethodDefinition(
            method_id=(
                f"contract_test.structure_annotation_{operation}.method"
            ),
            version=_VERSION,
            algorithm_identity={"name": "independent-deterministic-fixture"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "literal-values"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "identity"},
        )
        for operation in _OPERATIONS
    ),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
