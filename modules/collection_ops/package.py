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


_OPERATIONS = (
    "concat_candidates",
    "merge_scores",
    "concat_relations",
    "relate_by_parent",
    "relate_to_single_reference",
    "compose_relations",
    "invert_relation",
    "join_relation_subjects",
    "take_candidates",
    "select_related_subjects",
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
        node_type=ContractIdentity(
            "node_type",
            f"collection_ops.{operation}",
        ),
        method=ContractIdentity(
            "method",
            f"collection_ops.{operation}.method",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"collection_ops.{operation}/factory",
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"collection_ops.{operation}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        deterministic=True,
        cacheable=True,
        observation_propagation=propagation,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="collection_ops",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/concat_candidates.yaml"),
        DefinitionResource("definitions/merge_scores.yaml"),
        DefinitionResource("definitions/concat_relations.yaml"),
        DefinitionResource("definitions/relate_by_parent.yaml"),
        DefinitionResource("definitions/relate_to_single_reference.yaml"),
        DefinitionResource("definitions/compose_relations.yaml"),
        DefinitionResource("definitions/invert_relation.yaml"),
        DefinitionResource("definitions/join_relation_subjects.yaml"),
        DefinitionResource("definitions/take_candidates.yaml"),
        DefinitionResource("definitions/select_related_subjects.yaml"),
        DefinitionResource("definitions/intersect_candidates.yaml"),
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
)
