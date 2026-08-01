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
    FunctionAnnotations,
    ProteinPrompt,
    ResidueLayout,
    ResidueTrack,
)


_VERSION = "2.1.0"


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
        sequence_track = (
            ResidueTrack(["A", "C", "D"], None)
            if mode == "assigned_sequence"
            else (
                ResidueTrack([None, None, None], None)
                if mode == "coordinate_conditioned"
                else None
            )
        )
        structure_track = None
        visibility_track = None
        if mode == "coordinate_conditioned":
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
                secondary_structure_track=None,
                sasa_track=None,
                function_annotations=FunctionAnnotations([]),
            )
        return {"protein_prompt": prompt}


def _build(context: OperationContext) -> object:
    return _Source(context.resources)


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="contract_test.esm3_sources",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(DefinitionResource("definition.yaml"),),
    methods=(
        MethodDefinition(
            method_id="contract_test.esm3_prompt_source.method",
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
            binding_id="contract_test.esm3_prompt_source.direct",
            version=_VERSION,
            node_type=ContractIdentity(
                "node_type",
                "contract_test.esm3_prompt_source",
                _VERSION,
            ),
            method=ContractIdentity(
                "method",
                "contract_test.esm3_prompt_source.method",
                _VERSION,
            ),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/factory",
                    _VERSION,
                    {},
                ),
                build=_build,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/availability",
                    _VERSION,
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/readiness",
                    _VERSION,
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
