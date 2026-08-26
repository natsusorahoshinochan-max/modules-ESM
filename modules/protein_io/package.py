"""The single production registration for the protein I/O capability."""

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
from core.catalog.port_contract import BehaviorReference
from core.operation import OperationContext, ScientificOperation

from .implementation import (
    SequenceExportImplementation,
    SequenceImportImplementation,
    StructureExportImplementation,
    StructureImportImplementation,
)
from .port_types import ARTIFACT_PAYLOAD_PORT_TYPE


def _build(operation: str):
    def factory(context: OperationContext) -> ScientificOperation:
        if operation == "import_sequence":
            return SequenceImportImplementation(context.resources)
        if operation == "import_structure":
            return StructureImportImplementation(context.resources)
        if operation == "export_sequence":
            return SequenceExportImplementation(context.resources)
        return StructureExportImplementation(context.resources)

    return factory


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"protein_io.{operation}.direct",
        node_type=ContractIdentity(
            "node_type",
            f"protein_io.{operation}",
        ),
        method=ContractIdentity(
            "method",
            f"protein_io.{operation}.method",
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"protein_io.{operation}/factory",
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"protein_io.{operation}/availability",
                {"observation": "startup"},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        deterministic=True,
        cacheable=operation.startswith("export_"),
    )


_OPERATIONS = (
    "import_sequence",
    "import_structure",
    "export_sequence",
    "export_structure",
)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="protein_io",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/sequence_import.yaml"),
        DefinitionResource("definitions/structure_import.yaml"),
        DefinitionResource("definitions/sequence_export.yaml"),
        DefinitionResource("definitions/structure_export.yaml"),
    ),
    methods=load_method_definitions(
        __package__,
        "definitions/methods.yaml",
    ),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=(ARTIFACT_PAYLOAD_PORT_TYPE,),
)
