"""The single production registration for v2 collection operations."""

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
    ObservationPropagationDefinition,
    ReadinessDeclaration,
)

from .implementation import CollectionOpsImplementation


_VERSION = "2.0.0"
_OPERATIONS = ("concat_candidates", "merge_scores")


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(environment: Mapping[str, object]) -> bool:
    return isinstance(environment, Mapping)


def _build(operation: str):
    def factory(**kwargs: object) -> CollectionOpsImplementation:
        del kwargs
        return CollectionOpsImplementation(operation)

    return factory


def _method(operation: str) -> MethodDefinition:
    return MethodDefinition(
        method_id=f"collection_ops.{operation}.method",
        version=_VERSION,
        algorithm_identity={
            "name": operation,
            "input_partition_order": (
                ["candidates_a", "candidates_b", "candidates_c"]
                if operation == "concat_candidates"
                else ["scores_a", "scores_b", "scores_c"]
            ),
            "identity_policy": "exact-input-identity",
            "duplicate_policy": (
                "reject-candidate-partition-collision"
                if operation == "concat_candidates"
                else "deduplicate-identical-observation-only"
            ),
        },
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        source_identity={"kind": "repository-owned"},
        scale_contract={"kind": "identity"},
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    propagation = (
        ObservationPropagationDefinition(
            mode="union",
            output_port="scores",
            input_ports=("scores_a", "scores_b", "scores_c"),
            absent_input_policy="ignore",
        )
        if operation == "merge_scores"
        else None
    )
    return ExecutionBindingDefinition(
        binding_id=f"collection_ops.{operation}.direct",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"collection_ops.{operation}",
            _VERSION,
        ),
        method=ContractIdentity(
            "method",
            f"collection_ops.{operation}.method",
            _VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"collection_ops.{operation}/factory",
                _VERSION,
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"collection_ops.{operation}/availability",
                _VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"collection_ops.{operation}/readiness",
                _VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"collection_ops.{operation}.direct",
            "source": "repository-owned",
        },
        observation_propagation=propagation,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version=_VERSION,
    package_id="collection_ops",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/concat_candidates.yaml"),
        DefinitionResource("definitions/merge_scores.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
