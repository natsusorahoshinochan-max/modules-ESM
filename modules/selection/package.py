"""The single production registration for deterministic v2 selection."""

from __future__ import annotations

from core import (
    AvailabilityDeclaration,
    AvailabilityResult,
    BehaviorReference,
    ContractIdentity,
    DefinitionResource,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ObservationSelectorConsumptionDefinition,
    ReadinessCheckInput,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
    SelectionObjectiveConsumptionDefinition,
)
from core.operation import OperationContext

from .implementation import SelectionImplementation


PACKAGE_VERSION = "3.0.0"
METHOD_VERSION = "4.0.0"
NODE_BINDING_VERSION = "5.0.0"
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


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _factory(operation: str):
    def build(context: OperationContext) -> SelectionImplementation:
        return SelectionImplementation(
            operation=operation,
            objectives=context.selection_objectives,
            selectors=context.observation_selectors,
        )

    return build


def _method(operation: str) -> MethodDefinition:
    if operation == "weighted_rank":
        algorithm_identity = {
            "name": "normalized-weighted-utility-ranking",
            "candidate_score_join": "exact-candidate-data-reference",
            "weight_policy": "finite-non-negative-positive-total",
            "normalization": "divide-by-declared-weight-sum",
            "ranking": "descending-weighted-utility",
            "tie_policy": "candidate_id_ascending",
        }
    elif operation == "pareto":
        algorithm_identity = {
            "name": "dimensionless-utility-pareto-frontier",
            "candidate_score_join": "exact-candidate-data-reference",
            "dominance": "greater-or-equal-all-and-greater-any",
            "final_order": "candidate_id_ascending",
        }
    elif operation == "diversity":
        algorithm_identity = {
            "name": "weighted-max-min-euclidean-utility-diversity",
            "candidate_score_join": "exact-candidate-data-reference",
            "seed": "maximum-normalized-weighted-utility",
            "distance": "sqrt-sum-effective-weight-times-squared-delta",
            "iteration": "maximum-minimum-distance",
            "tie_policy": "candidate_id_ascending",
        }
    else:
        algorithm_identity = {
            "name": f"deterministic-candidate-{operation}",
            "candidate_score_join": "exact-candidate-data-reference",
            "objective_scope": "workflow-owned-exact-source",
            "match_cardinality": "exactly_one",
            "missing_policy": "error",
            "out_of_scope_default": "error",
            "tie_policy": "candidate_id_ascending",
            "ranking_scale": (
                "exact-utility-transform"
                if operation in {"sort", "top_k"}
                else "canonical-metric-value"
            ),
        }
    return MethodDefinition(
        method_id=f"selection.{operation}.method",
        version=METHOD_VERSION,
        algorithm_identity=algorithm_identity,
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        source_identity={"kind": "repository-owned"},
        scale_contract={
            "kind": (
                "dimensionless-utility-vector"
                if operation in MULTI_OBJECTIVE_OPERATIONS
                else
                "workflow-objective-utility"
                if operation in {"sort", "top_k"}
                else "exact-metric-canonical-scale"
            )
        },
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"selection.{operation}.direct",
        version=NODE_BINDING_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"selection.{operation}",
            NODE_BINDING_VERSION,
        ),
        method=ContractIdentity(
            "method",
            f"selection.{operation}.method",
            METHOD_VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"selection.{operation}/factory",
                NODE_BINDING_VERSION,
                {"execution_route": "direct"},
            ),
            build=_factory(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"selection.{operation}/availability",
                NODE_BINDING_VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"selection.{operation}/readiness",
                NODE_BINDING_VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"selection.{operation}.direct",
            "source": "repository-owned",
            "identity_preservation": "exact-candidate-object",
        },
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
    schema_version="2.1.0",
    package_id="selection",
    package_version=PACKAGE_VERSION,
    package_module=__package__,
    node_definitions=tuple(
        DefinitionResource(f"definitions/{operation}.yaml")
        for operation in OPERATIONS
    ),
    methods=tuple(_method(operation) for operation in OPERATIONS),
    bindings=tuple(_binding(operation) for operation in OPERATIONS),
)
