"""The single production registration for residue data."""

from __future__ import annotations

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ScientificOperationFactory,
)
from core.catalog.definition_resource import (
    DefinitionResource,
    load_method_definitions,
)
from core.catalog.port_contract import (
    BehaviorReference,
)
from core.operation import OperationContext, ScientificOperation

from .implementation import MaterializeSequenceImplementation
from .port_types import RESIDUE_CONDITION_PORT_TYPES


def _factory(context: OperationContext) -> ScientificOperation:
    return MaterializeSequenceImplementation()


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _binding() -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id="residue_data.materialize_sequence.direct",
        node_type=ContractIdentity(
            "node_type",
            "residue_data.materialize_sequence",
        ),
        method=ContractIdentity(
            "method",
            "residue_data.materialize_sequence.method",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                "residue_data.materialize_sequence/factory",
                {"execution_route": "direct"},
            ),
            build=_factory,
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                "residue_data.materialize_sequence/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        deterministic=True,
        cacheable=True,
    )


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="residue_data",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/materialize_sequence.yaml"),
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=(_binding(),),
    port_types=RESIDUE_CONDITION_PORT_TYPES,
)
