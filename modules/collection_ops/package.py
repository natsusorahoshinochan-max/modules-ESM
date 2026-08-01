"""The single production registration for v2 collection operations."""

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
    ObservationPropagationDefinition,
    ReadinessCheckInput,
    ReadinessDeclaration,
    ReadinessResult,
    ScientificOperationFactory,
)
from core.operation import OperationContext

from .implementation import CollectionOpsImplementation


_VERSION = "2.1.0"
_OPERATIONS = (
    "concat_candidates",
    "merge_scores",
    "pair_siblings_by_parent",
    "rebind_candidate_pairing",
    "take_candidates",
)


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _build(operation: str):
    def factory(context: OperationContext) -> CollectionOpsImplementation:
        del context
        return CollectionOpsImplementation(operation)

    return factory


def _method(operation: str) -> MethodDefinition:
    input_partition_order = {
        "concat_candidates": [
            "candidates_a",
            "candidates_b",
            "candidates_c",
        ],
        "merge_scores": ["scores_a", "scores_b", "scores_c"],
        "pair_siblings_by_parent": ["subjects", "references"],
        "rebind_candidate_pairing": [
            "subjects",
            "parents",
            "references",
            "parent_pairing",
        ],
        "take_candidates": ["candidates"],
    }[operation]
    duplicate_policy = {
        "concat_candidates": "reject-candidate-partition-collision",
        "merge_scores": "deduplicate-identical-observation-only",
        "pair_siblings_by_parent": "one-sibling-per-common-parent",
        "rebind_candidate_pairing": "complete-one-to-one-parent-composition",
        "take_candidates": "preserve-exact-ordered-prefix",
    }[operation]
    return MethodDefinition(
        method_id=f"collection_ops.{operation}.method",
        version=_VERSION,
        algorithm_identity={
            "name": operation,
            "input_partition_order": input_partition_order,
            "identity_policy": "exact-input-identity",
            "duplicate_policy": duplicate_policy,
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
        factory=ScientificOperationFactory(
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
    schema_version="2.1.0",
    package_id="collection_ops",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/concat_candidates.yaml"),
        DefinitionResource("definitions/merge_scores.yaml"),
        DefinitionResource("definitions/pair_siblings_by_parent.yaml"),
        DefinitionResource("definitions/rebind_candidate_pairing.yaml"),
        DefinitionResource("definitions/take_candidates.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
