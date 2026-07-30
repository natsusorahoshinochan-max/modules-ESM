"""The single production registration for deterministic v2 selection."""

from __future__ import annotations

from collections.abc import Mapping

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
    SelectionObjectiveConsumptionDefinition,
)

from .implementation import SelectionImplementation


VERSION = "2.0.0"
OPERATIONS = ("filter", "sort", "top_k")


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(environment: Mapping[str, object]) -> bool:
    return isinstance(environment, Mapping)


def _factory(operation: str):
    def build(**kwargs: object) -> SelectionImplementation:
        return SelectionImplementation(
            operation=operation,
            execution_plan=kwargs["execution_plan"],
            catalog=kwargs["frozen_catalog"],
        )

    return build


def _method(operation: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"selection.{operation}.method",
        version=VERSION,
        algorithm_identity={
            "name": f"deterministic-candidate-{operation}",
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
        },
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        source_identity={"kind": "repository-owned"},
        scale_contract={
            "kind": (
                "workflow-objective-utility"
                if operation in {"sort", "top_k"}
                else "exact-metric-canonical-scale"
            )
        },
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"selection.{operation}.direct",
        version=VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"selection.{operation}",
            VERSION,
        ),
        method=ContractIdentity(
            "method",
            f"selection.{operation}.method",
            VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"selection.{operation}/factory",
                VERSION,
                {"execution_route": "direct"},
            ),
            build=_factory(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"selection.{operation}/availability",
                VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"selection.{operation}/readiness",
                VERSION,
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
            SelectionObjectiveConsumptionDefinition(
                objective_id_parameter="objective_id",
                candidate_input_port="candidates",
                score_collection_input_port="scores",
            )
        ),
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=VERSION,
    package_id="selection",
    package_version=VERSION,
    package_module=__package__,
    node_definitions=tuple(
        DefinitionResource(f"definitions/{operation}.yaml")
        for operation in OPERATIONS
    ),
    methods=tuple(_method(operation) for operation in OPERATIONS),
    bindings=tuple(_binding(operation) for operation in OPERATIONS),
)
