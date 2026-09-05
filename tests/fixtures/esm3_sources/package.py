"""Independent source registration for remote ESM-3 acceptance."""

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
from datatypes.prompt import (
    FunctionAnnotation,
    ProteinPrompt,
)
from datatypes.residue import (
    ResidueLayout,
    ResidueTrack,
)
from datatypes.structure import NamedAtomCoordinates


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
        length = 291 if mode == "coordinate_conditioned_291" else 3
        layout = ResidueLayout(
            [f"A:{index}" for index in range(1, length + 1)]
        )
        if mode in {"assigned_sequence", "rich_assigned"}:
            sequence_carrier = ResidueTrack(layout, ["A", "C", "D"])
        elif mode == "rich_masked":
            sequence_carrier = ResidueTrack(layout, [None, "C", "D"])
        else:
            sequence_carrier = ResidueTrack(layout, [None] * length)
        structure_carrier = ResidueTrack(layout, [None] * length)
        if mode in {
            "coordinate_conditioned",
            "coordinate_conditioned_291",
            "rich_assigned",
            "rich_masked",
        }:
            first_coords = NamedAtomCoordinates.from_mapping({
                "N": (0.0, 0.0, 0.0),
                "CA": (1.0, 0.0, 0.0),
                "C": (2.0, 0.0, 0.0),
                "O": (3.0, 0.0, 0.0),
            })
            structure_carrier = ResidueTrack(
                layout,
                [first_coords, *([None] * (length - 1))],
            )
        rich_prompt = mode in {"rich_assigned", "rich_masked"}
        with self._run_resources.engine_invocation():
            prompt = ProteinPrompt(
                layout=layout,
                sequence=tuple(sequence_carrier.values),
                coordinates=tuple(structure_carrier.values),
                secondary_structure=(
                    ("G", "C", None) if rich_prompt else None
                ),
                sasa=(
                    (0.0, 16.4, None) if rich_prompt else None
                ),
                function_annotations=(
                    (
                        FunctionAnnotation(
                            label="binding site",
                            start_residue_id="A:1",
                            end_residue_id="A:2",
                        ),
                    )
                    if rich_prompt
                    else ()
                ),
            )
        return {"protein_prompt": prompt}


def _build(context: OperationContext) -> object:
    return _Source(context.resources)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="contract_test.esm3_sources",
    package_module=__package__,
    node_definitions=(DefinitionResource("definition.yaml"),),
    methods=(
        MethodDefinition(
            method_id="contract_test.esm3_prompt_source.method",
            algorithm_identity={"name": "independent-deterministic-fixture"},
            model_identity={"kind": "none"},
            featurization_identity={"kind": "literal-values"},
            scale_contract={"kind": "identity"},
        ),
    ),
    bindings=(
        ExecutionBindingDefinition(
            binding_id="contract_test.esm3_prompt_source.direct",
            node_type=ContractIdentity(
                "node_type",
                "contract_test.esm3_prompt_source"),
            method=ContractIdentity(
                "method",
                "contract_test.esm3_prompt_source.method"),
            binding_parameters={},
            execution_route="direct",
            factory=ScientificOperationFactory(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/factory",
                    {},
                ),
                build=_build,
            ),
            availability=AvailabilityDeclaration(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/availability",
                    {},
                ),
                prerequisites={},
                check=AvailabilityResult.available,
            ),
            readiness=ReadinessDeclaration(
                behavior=BehaviorReference(
                    "contract_test.esm3_prompt_source/readiness",
                    {},
                ),
                prerequisites={},
                check=lambda environment: ReadinessResult(True),
            ),
            deterministic=True,
            cacheable=True),
    ),
)
