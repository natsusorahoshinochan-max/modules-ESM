"""The single production registration for deterministic v2 selection."""

from __future__ import annotations

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    CandidateSelectionConsumptionDefinition,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ModuleUiDefinition,
    NodeEditorDefinition,
    ObservationSelectorConsumptionDefinition,
    ScientificOperationFactory,
    SelectionObjectiveConsumptionDefinition,
)
from datatypes.exact_reference import ExactContractReference
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
    "manual",
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
        node_type=ExactContractReference(
            "node_type",
            f"selection.{operation}",
        ),
        method=ExactContractReference(
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
            if operation in {"filter", "manual"}
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
                selector_ids_parameter="selector_ids",
            )
            if operation == "filter"
            else None
        ),
        candidate_selection_consumption=(
            CandidateSelectionConsumptionDefinition(
                candidate_input_port="candidates",
                candidate_output_port="candidates",
            )
            if operation == "manual"
            else None
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="selection",
    package_module=__package__,
    ui_extensions=(ModuleUiDefinition(
        extension_id="selection.editors", resource_package=__package__,
        entry="ui/build/editor.js", styles=("ui/build/editor.css",), react_major=19,
        editors=(NodeEditorDefinition(
            editor_id="selection.editor", title="编辑筛选与排序",
            node_type_ids=tuple(f"selection.{operation}" for operation in OPERATIONS),
            component="SelectionEditor",
        ),),
    ),),
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
