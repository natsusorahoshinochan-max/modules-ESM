"""The single production registration for deterministic v2 selection."""

from __future__ import annotations

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ObservationSelectorConsumptionDefinition,
    ScientificOperationFactory,
    SelectionObjectiveConsumptionDefinition,
)
from core.catalog.definition_resource import (
    DefinitionResource,
    load_method_definitions,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import OperationContext

from .implementation import SelectionImplementation


OPERATIONS = (
    "filter",
    "sort",
    "top_k",
    "weighted_rank",
    "pareto",
    "diversity",
)
MULTI_OBJECTIVE_OPERATIONS = frozenset(
    {"weighted_rank", "pareto", "diversity"}
)


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _factory(operation: str):
    def build(context: OperationContext) -> SelectionImplementation:
        return SelectionImplementation(
            operation=operation,
            objectives=context.selection_objectives,
            selectors=context.observation_selectors,
        )

    return build


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"selection.{operation}.direct",
        node_type=ContractIdentity(
            "node_type",
            f"selection.{operation}",
        ),
        method=ContractIdentity(
            "method",
            f"selection.{operation}.method",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"selection.{operation}/factory",
                {"execution_route": "direct"},
            ),
            build=_factory(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"selection.{operation}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        deterministic=True,
        cacheable=True,
        selection_objective_consumption=(
            None
            if operation == "filter"
            else SelectionObjectiveConsumptionDefinition(
                candidate_input_port="candidates",
                score_collection_input_port="scores",
                candidate_output_port="candidates",
                **(
                    {"objective_ids_parameter": "objective_ids"}
                    if operation in MULTI_OBJECTIVE_OPERATIONS
                    else {"objective_id_parameter": "objective_id"}
                ),
            )
        ),
        observation_selector_consumption=(
            ObservationSelectorConsumptionDefinition(
                candidate_input_port="candidates",
                score_collection_input_port="scores",
                candidate_output_port="candidates",
                selector_id_parameter="selector_id",
            )
            if operation == "filter"
            else None
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="selection",
    package_module=__package__,
    node_definitions=tuple(
        DefinitionResource(f"definitions/{operation}.yaml")
        for operation in OPERATIONS
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=tuple(_binding(operation) for operation in OPERATIONS),
)
