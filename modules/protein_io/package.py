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


_PACKAGE_VERSION = "3.0.0"
_OPERATION_VERSIONS = {
    "import_sequence": "6.0.0",
    "import_structure": "6.0.0",
    "export_sequence": "3.0.0",
    "export_structure": "6.0.0",
}
_METHOD_VERSIONS = {
    "import_sequence": "4.0.0",
    "import_structure": "2.1.0",
    "export_sequence": "2.1.0",
    "export_structure": "2.1.0",
}


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
    version = _OPERATION_VERSIONS[operation]
    return ExecutionBindingDefinition(
        binding_id=f"protein_io.{operation}.direct",
        version=version,
        node_type=ContractIdentity(
            "node_type",
            f"protein_io.{operation}",
            version,
        ),
        method=ContractIdentity(
            "method",
            f"protein_io.{operation}.method",
            _METHOD_VERSIONS[operation],
        ),
        binding_parameters={},
        execution_route="direct",
        factory=ScientificOperationFactory(
            behavior=BehaviorReference(
                f"protein_io.{operation}/factory",
                version,
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"protein_io.{operation}/availability",
                version,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=AvailabilityResult.available,
        ),
        deterministic=True,
        cacheable=operation.startswith("export_"),
        implementation_identity={
            "name": f"protein_io.{operation}.direct",
            "source": "repository-owned",
        },
    )


_OPERATIONS = (
    "import_sequence",
    "import_structure",
    "export_sequence",
    "export_structure",
)


MODULE_PACKAGE = ModulePackageRegistration(
    package_id="protein_io",
    package_version=_PACKAGE_VERSION,
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
