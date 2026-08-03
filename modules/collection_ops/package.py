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


_PACKAGE_VERSION = "3.0.0"
_METHOD_VERSION = "2.1.0"
_PAIRING_METHOD_VERSION = "3.0.0"
_CANDIDATE_NODE_BINDING_VERSION = "3.0.0"
_SCORE_NODE_BINDING_VERSION = "4.0.0"
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
    algorithm_identity: dict[str, object] = {
        "name": operation,
        "input_partition_order": input_partition_order,
        "identity_policy": "exact-input-identity",
        "duplicate_policy": duplicate_policy,
    }
    if operation in {
        "pair_siblings_by_parent",
        "rebind_candidate_pairing",
    }:
        algorithm_identity["pairing_contract"] = {
            "participant_identity": "CandidateDataReference",
            "join": "complete-reference-equality",
            "cardinality": "one-to-one",
        }
    return MethodDefinition(
        method_id=f"collection_ops.{operation}.method",
        version=(
            _PAIRING_METHOD_VERSION
            if operation
            in {"pair_siblings_by_parent", "rebind_candidate_pairing"}
            else _METHOD_VERSION
        ),
        algorithm_identity=algorithm_identity,
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "identity"},
        source_identity={"kind": "repository-owned"},
        scale_contract={"kind": "identity"},
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    node_binding_version = (
        _SCORE_NODE_BINDING_VERSION
        if operation == "merge_scores"
        else _CANDIDATE_NODE_BINDING_VERSION
    )
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
        version=node_binding_version,
        node_type=ContractIdentity(
            "node_type",
            f"collection_ops.{operation}",
            node_binding_version,
        ),
        method=ContractIdentity(
            "method",
            f"collection_ops.{operation}.method",
            (
                _PAIRING_METHOD_VERSION
                if operation
                in {"pair_siblings_by_parent", "rebind_candidate_pairing"}
                else _METHOD_VERSION
            ),
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"collection_ops.{operation}/factory",
                node_binding_version,
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"collection_ops.{operation}/availability",
                node_binding_version,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"collection_ops.{operation}/readiness",
                node_binding_version,
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
    package_version=_PACKAGE_VERSION,
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
