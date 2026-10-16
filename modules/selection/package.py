"""The single production registration for deterministic v2 selection."""

from __future__ import annotations

from core.catalog.result_adoption import ResultSourceDefinition

from core.catalog.result_reading import ResultReaderDefinition
from .published_reading import read_scores
from .adopted_scores import AdoptedScoreOperation, adopted_observations, adopted_dependencies

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    CandidateSelectionConsumptionDefinition,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ModuleUiDefinition,
    NodeEditorDefinition,
    ScientificOperationFactory,
    SelectionObjectiveConsumptionDefinition,
    ParameterDependencyDeclaration,
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
from .operation import RawSelectionOperation
from .weighted import WeightedSelectionOperation, weighted_dependencies
from .result_actions import VIEW_CANDIDATES_ACTION


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
    {"diversity"}
)


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _factory(operation: str):
    def build(context: OperationContext):
        if operation == "weighted_rank":
            return WeightedSelectionOperation(context.resolved_definitions)
        if operation in {"filter", "sort", "top_k", "pareto"}:
            return RawSelectionOperation(operation)
        return SelectionImplementation(
            operation=operation,
            objectives=context.selection_objectives,
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
        parameter_dependencies=(ParameterDependencyDeclaration(
            BehaviorReference("selection.weighted_rank/parameter_dependencies", {"terms": "positive-weight"}),
            weighted_dependencies) if operation == "weighted_rank" else None),
        selection_objective_consumption=(
            None
            if operation in {"filter", "manual", "sort", "top_k", "pareto", "weighted_rank"}
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
        candidate_selection_consumption=(
            CandidateSelectionConsumptionDefinition(
                candidate_input_port="candidates",
                candidate_output_port="candidates",
            )
            if operation == "manual"
            else None
        ),
    )


_ADOPT_BINDING = ExecutionBindingDefinition(
    binding_id="selection.adopt_scores.direct",
    node_type=ExactContractReference("node_type", "selection.adopt_scores"),
    method=ExactContractReference("method", "selection.adopt_scores.method"),
    binding_parameters={}, execution_route="direct",
    factory=ScientificOperationFactory(BehaviorReference("selection.adopt_scores/factory"),
        lambda context: AdoptedScoreOperation(context.resources)),
    availability=AvailabilityDeclaration(BehaviorReference("selection.adopt_scores/availability"), {}, _available),
    deterministic=True, cacheable=False,
)


MODULE_PACKAGE = ModulePackageRegistration(
    result_actions=(VIEW_CANDIDATES_ACTION,),
    result_sources=(ResultSourceDefinition("score.collection", "selection.adopt_scores", "selection.adopt_scores.direct", observations=adopted_observations, dependencies=adopted_dependencies),),
    result_readers=(
        ResultReaderDefinition("score.collection", "scores", read_scores),
    ),
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
    node_definitions=(DefinitionResource("definitions/adopt_scores.yaml"),) + tuple(
        DefinitionResource(f"definitions/{operation}.yaml")
        for operation in OPERATIONS
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=(_ADOPT_BINDING,) + tuple(_binding(operation) for operation in OPERATIONS),
)
