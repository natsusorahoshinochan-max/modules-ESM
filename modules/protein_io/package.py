"""The single production registration for the protein I/O capability."""

from __future__ import annotations

from core.catalog.ui import ModuleUiDefinition, ResultViewerDefinition

from core.catalog.result_reading import ResultReaderDefinition
from .published_reading import read_sequence
from .published_reading import read_structure

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ExecutionBindingDefinition,
    ModulePackageRegistration,
    ScientificOperationFactory,
)
from datatypes.exact_reference import ExactContractReference
from core.catalog.definition_resource import (
    DefinitionResource,
    load_method_definitions,
)
from core.catalog.port_contract import BehaviorReference
from core.operation import OperationContext, ScientificOperation

from .implementation import (
    SequenceBatchImportImplementation,
    SequenceExportImplementation,
    SequenceImportImplementation,
    StructureExportImplementation,
    StructureImportImplementation,
)
from .port_types import ARTIFACT_PAYLOAD_PORT_TYPE
from .structure_export import EXPORT_STRUCTURE_ACTION


def _build(operation: str):
    def factory(context: OperationContext) -> ScientificOperation:
        if operation == "import_sequence":
            return SequenceImportImplementation(context.resources)
        if operation == "import_sequences":
            return SequenceBatchImportImplementation(context.resources)
        if operation == "import_structure":
            return StructureImportImplementation(context.resources)
        if operation == "export_sequence":
            return SequenceExportImplementation(context.resources)
        return StructureExportImplementation(context.resources)

    return factory


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"protein_io.{operation}.direct",
        node_type=ExactContractReference(
            "node_type",
            f"protein_io.{operation}",
        ),
        method=ExactContractReference(
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
    "import_sequences",
    "import_structure",
    "export_sequence",
    "export_structure",
)


MODULE_PACKAGE = ModulePackageRegistration(
    result_readers=(
        ResultReaderDefinition("protein.sequence", "sequence", read_sequence),
        ResultReaderDefinition("protein.structure", "structure", read_structure),
    ),
    ui_extensions=(ModuleUiDefinition(
        extension_id="protein_io.viewers", resource_package=__package__,
        entry="ui/build/viewers.js", styles=("ui/build/viewers.css",), react_major=19,
        editors=(), viewers=(
            ResultViewerDefinition("protein_io.sequence", "序列", "protein.sequence", "Sequence", True),
            ResultViewerDefinition("protein_io.structure.3d", "三维结构", "protein.structure", "Structure3D", True),
            ResultViewerDefinition("protein_io.structure.text", "结构原文", "protein.structure", "StructureText"),
        ),
    ),),
    package_id="protein_io",
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/sequence_import.yaml"),
        DefinitionResource("definitions/sequences_import.yaml"),
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
    result_actions=(EXPORT_STRUCTURE_ACTION,),
)
