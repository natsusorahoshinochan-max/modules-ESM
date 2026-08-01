"""Independent source registration for structure-annotation acceptance."""

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
from datatypes import Candidate, CandidateCollection, ProteinStructure, ResidueLayout
from modules.structure_annotation import (
    DSSPAnnotation,
    StructureAnnotationTrack,
)


_VERSION = "2.1.0"
_NODE_BINDING_VERSION = "3.0.0"


class _Source:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or node_parameters or binding_parameters:
            raise ValueError("structure annotation source accepts no values")
        layout = ResidueLayout(
            chain_id="A",
            length=2,
            residue_ids=["A:1", "A:2"],
        )
        structure = ProteinStructure(
            pdb_string=(
                "ATOM      1  CA  GLY A   1       "
                "1.000   2.000   3.000  1.00 20.00           C\n"
                "ATOM      2  CA  ALA A   2       "
                "2.000   3.000   4.000  1.00 20.00           C\n"
                "TER\nEND\n"
            ),
        )
        with self._run_resources.engine_invocation():
            annotations = DSSPAnnotation(
                layout=layout,
                secondary_structure=("H", "C"),
                sasa=(10.0, 20.0),
            )
            expected = StructureAnnotationTrack(
                layout=layout,
                values=("H", "E"),
            )
            observed = StructureAnnotationTrack(
                layout=layout,
                values=("G", "E"),
            )
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
        return {
            "structure": structure,
            "annotations": annotations,
            "expected": expected,
            "observed": observed,
            "subjects": subjects,
            "references": references,
        }


def _build(context: OperationContext) -> object:
    return _Source(context.resources)


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.structure_annotation_sources",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(DefinitionResource("definition.yaml"),),
    methods=(
        MethodDefinition(
            method_id="contract_test.structure_annotation_source.method",
            version=_VERSION,
            algorithm_identity={"name": "independent-deterministic-fixture"},
            model_identity={"kind": "none"},
            checkpoint_identity={"kind": "none"},
            featurization_identity={"kind": "literal-values"},
            source_identity={"kind": "contract-test-fixture"},
            scale_contract={"kind": "identity"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.structure_annotation_source.direct",
            version=_NODE_BINDING_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.structure_annotation_source",
                _NODE_BINDING_VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.structure_annotation_source.method",
                _VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.structure_annotation_source/factory",
                    _VERSION,
                    {},
                ),
                build=_build,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.structure_annotation_source/availability",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.structure_annotation_source/readiness",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "contract_test.structure_annotation_source.direct",
                "source": "contract-test-fixture",
            },
        ),
    ),
)
