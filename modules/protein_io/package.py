"""The single production registration for the protein I/O capability."""

from __future__ import annotations

import base64
import re

from core.catalog.declarations import (
    AvailabilityDeclaration,
    AvailabilityResult,
    ContractIdentity,
    ExecutionBindingDefinition,
    MethodDefinition,
    ModulePackageRegistration,
    ReadinessDeclaration,
    ScientificOperationFactory,
)
from core.catalog.definition_resource import (
    DefinitionResource,
)
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
)
from core.operation import (
    ArtifactPayload,
    OperationContext,
    ReadinessCheckInput,
    ReadinessResult,
    ScientificOperation,
)

from .implementation import (
    SequenceExportImplementation,
    SequenceImportImplementation,
    StructureExportImplementation,
    StructureImportImplementation,
)


_PACKAGE_VERSION = "3.0.0"
_ARTIFACT_PORT_VERSION = "2.1.0"
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
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _validate_artifact_payload(value: object) -> None:
    if type(value) is not ArtifactPayload:
        raise ValueError("artifact payload has the wrong runtime type")
    if type(value.body) is not bytes or len(value.body) > 64 * 1024 * 1024:
        raise ValueError("artifact body is invalid or too large")
    if (
        value.media_type not in {"text/x-fasta", "chemical/x-pdb"}
        or _SAFE_NAME.fullmatch(value.filename) is None
    ):
        raise ValueError("artifact metadata is invalid")


def _artifact_to_wire(value: object) -> object:
    assert isinstance(value, ArtifactPayload)
    return {
        "body_base64": base64.b64encode(value.body).decode("ascii"),
        "media_type": value.media_type,
        "filename": value.filename,
        "candidate_id": value.candidate_id,
    }


def _artifact_from_wire(value: object) -> object:
    if not isinstance(value, dict) or set(value) != {
        "body_base64",
        "media_type",
        "filename",
        "candidate_id",
    }:
        raise ValueError("artifact wire value is invalid")
    body_value = value["body_base64"]
    if not isinstance(body_value, str):
        raise ValueError("artifact body encoding is invalid")
    return ArtifactPayload(
        body=base64.b64decode(body_value, validate=True),
        media_type=value["media_type"],
        filename=value["filename"],
        candidate_id=value["candidate_id"],
    )


def _build(operation: str):
    def factory(context: OperationContext) -> ScientificOperation:
        if operation == "import_sequence":
            return SequenceImportImplementation(context.resources)
        if operation == "import_structure":
            return StructureImportImplementation(context.resources)
        if operation == "export_sequence":
            return SequenceExportImplementation(context.resources)
        if operation == "export_structure":
            return StructureExportImplementation(context.resources)
        raise RuntimeError("protein I/O implementation is not installed")

    return factory


def _method(operation: str) -> MethodDefinition:
    version = _METHOD_VERSIONS[operation]
    return MethodDefinition(
        method_id=f"protein_io.{operation}.method",
        version=version,
        algorithm_identity={"name": operation, "format_contract": version},
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={"kind": "canonical-protein-io"},
        source_identity={"kind": "repository-owned"},
        scale_contract={"kind": "identity"},
    )


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
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"protein_io.{operation}/readiness",
                version,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
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
    schema_version="2.1.0",
    package_id="protein_io",
    package_version=_PACKAGE_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/sequence_import.yaml"),
        DefinitionResource("definitions/structure_import.yaml"),
        DefinitionResource("definitions/sequence_export.yaml"),
        DefinitionResource("definitions/structure_export.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=(
        PortTypeDefinition(
            type_id="protein_io.artifact_payload",
            version=_ARTIFACT_PORT_VERSION,
            validator=BehaviorReference(
                "protein_io.artifact_payload/validate",
                _ARTIFACT_PORT_VERSION,
                {
                    "accepted_value_kind": "artifact_payload",
                    "artifact_publication": {
                        "media_types": [
                            "chemical/x-pdb",
                            "text/x-fasta",
                        ],
                    },
                },
            ),
            codec=BehaviorReference(
                "protein_io.artifact_payload/codec",
                _ARTIFACT_PORT_VERSION,
                {
                    "canonicalization": "RFC 8785",
                    "binary_encoding": "base64",
                },
            ),
            content_identity=BehaviorReference(
                "protein_io.artifact_payload/content",
                _ARTIFACT_PORT_VERSION,
                {"digest": "SHA-256"},
            ),
            runtime_validator=_validate_artifact_payload,
            runtime_to_wire=_artifact_to_wire,
            runtime_from_wire=_artifact_from_wire,
        ),
    ),
)
