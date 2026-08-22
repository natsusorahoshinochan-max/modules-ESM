"""The single production registration for v2 collection operations."""

from __future__ import annotations

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ObservationPropagationDefinition,
    ScientificOperationFactory,
)
from core.catalog.definition_resource import (
    DefinitionResource,
    load_method_definitions,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import OperationContext

from .implementation import CollectionOpsImplementation


_PACKAGE_VERSION = "4.0.0"
_METHOD_VERSION = "2.1.0"
_PAIRING_METHOD_VERSION = "3.0.0"
_CANDIDATE_NODE_BINDING_VERSION = "4.0.0"
_SCORE_NODE_BINDING_VERSION = "5.0.0"
_OPERATIONS = (
    "concat_candidates",
    "merge_scores",
    "concat_pairings",
    "pair_siblings_by_parent",
    "rebind_candidate_pairing",
    "take_candidates",
    "select_children_by_parent",
    "intersect_candidates",
)


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _build(operation: str):
    def factory(context: OperationContext) -> CollectionOpsImplementation:
        del context
        return CollectionOpsImplementation(operation)

    return factory


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
                in {
                    "concat_pairings",
                    "pair_siblings_by_parent",
                    "rebind_candidate_pairing",
                }
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
        DefinitionResource("definitions/concat_pairings.yaml"),
        DefinitionResource("definitions/pair_siblings_by_parent.yaml"),
        DefinitionResource("definitions/rebind_candidate_pairing.yaml"),
        DefinitionResource("definitions/take_candidates.yaml"),
        DefinitionResource("definitions/select_children_by_parent.yaml"),
        DefinitionResource("definitions/intersect_candidates.yaml"),
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
