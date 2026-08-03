"""Independent source registration for remote ESM-3 acceptance."""

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
    FunctionAnnotation,
    FunctionAnnotations,
    ProteinPrompt,
    ResidueLayout,
    ResidueTrack,
)


_PACKAGE_VERSION = "2.1.0"
_METHOD_VERSION = "2.1.0"
_NODE_BINDING_VERSION = "3.0.0"


class _Source:
    def __init__(self, run_resources: Any) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if inputs or set(node_parameters) != {"mode"} or binding_parameters:
            raise ValueError("ESM-3 prompt source accepts only resolved mode")
        mode = node_parameters["mode"]
        if mode in {"assigned_sequence", "rich_assigned"}:
            sequence_track = ResidueTrack(["A", "C", "D"], None)
        elif mode == "rich_masked":
            sequence_track = ResidueTrack([None, "C", "D"], None)
        elif mode == "coordinate_conditioned":
            sequence_track = ResidueTrack([None, None, None], None)
        else:
            sequence_track = None
        structure_track = None
        visibility_track = None
        if mode in {
            "coordinate_conditioned",
            "rich_assigned",
            "rich_masked",
        }:
            structure_track = ResidueTrack(
                [
                    {
                        "N": (0.0, 0.0, 0.0),
                        "CA": (1.0, 0.0, 0.0),
                        "C": (2.0, 0.0, 0.0),
                        "O": (3.0, 0.0, 0.0),
                    },
                    None,
                    None,
                ],
                None,
            )
            visibility_track = ResidueTrack([True, False, False], None)
        rich_prompt = mode in {"rich_assigned", "rich_masked"}
        with self._run_resources.engine_invocation():
            prompt = ProteinPrompt(
                target_layout=ResidueLayout(
                    chain_id="A",
                    length=3,
                    residue_ids=["A:1", "A:2", "A:3"],
                ),
                sequence_track=sequence_track,
                structure_track=structure_track,
                structure_visibility_track=visibility_track,
                secondary_structure_track=(
                    ResidueTrack(["G", "-", None], None)
                    if rich_prompt
                    else None
                ),
                sasa_track=(
                    ResidueTrack([0.0, 16.4, None], None)
                    if rich_prompt
                    else None
                ),
                function_annotations=FunctionAnnotations(
                    [
                        FunctionAnnotation(
                            label="binding site",
                            start=1,
                            end=2,
                            chain_id="A",
                            start_residue_id="A:1",
                            end_residue_id="A:2",
                            overlap_policy="reject",
                        )
                    ]
                    if rich_prompt
                    else []
                ),
            )
        return {"protein_prompt": prompt}


def _build(context: OperationContext) -> object:
    return _Source(context.resources)


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.esm3_sources",
    package_version=_PACKAGE_VERSION,
    package_module=__package__,
    node_definitions=(DefinitionResource("definition.yaml"),),
    methods=(
        MethodDefinition(
            method_id="contract_test.esm3_prompt_source.method",
            version=_METHOD_VERSION,
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
            binding_id="contract_test.esm3_prompt_source.direct",
            version=_NODE_BINDING_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.esm3_prompt_source",
                _NODE_BINDING_VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.esm3_prompt_source.method",
                _METHOD_VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/factory",
                    _NODE_BINDING_VERSION,
                    {},
                ),
                build=_build,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/availability",
                    _NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/readiness",
                    _NODE_BINDING_VERSION,
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True,
            implementation_identity={
                "name": "contract_test.esm3_prompt_source.direct",
                "source": "contract-test-fixture",
            },
        ),
    ),
)
