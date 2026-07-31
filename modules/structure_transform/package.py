"""The single production registration for structure transformations."""

from __future__ import annotations

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
    PortTypeDefinition,
    ReadinessCheckInput,
    ReadinessDeclaration,
    ReadinessResult,
)
from datatypes import ProteinStructure

from .implementation import (
    StructureTransformImplementation,
    validate_backbone_structure,
)


_VERSION = "2.1.0"
_OPERATIONS = (
    "select_chains",
    "extract_backbone",
    "extract_sequence",
    "backbone_to_structure",
)


def _available() -> AvailabilityResult:
    return AvailabilityResult.available()


def _ready(check_input: ReadinessCheckInput) -> ReadinessResult:
    del check_input
    return ReadinessResult(True)


def _build(operation: str):
    def factory(**kwargs: object) -> object:
        return StructureTransformImplementation(
            kwargs["run_resources"],
            operation,
        )

    return factory


def _method(operation: str) -> MethodDefinition:
    algorithm_identity = {
        "select_chains": {
            "name": "ordered-exact-pdb-chain-selection",
            "chain_identity": "one-alphanumeric-PDB-chain-ID",
            "ordering": "workflow-request-order",
            "multi_model": "reject",
            "records": ["ATOM", "HETATM"],
            "chain_breaks": "canonical-TER-per-retained-segment",
        },
        "extract_backbone": {
            "name": "complete-canonical-protein-backbone-extraction",
            "retained_records": ["ATOM"],
            "retained_atoms": ["N", "CA", "C", "O"],
            "retained_residues": "every-contiguous-ATOM-residue",
            "missing_atoms": "reject-residue-and-operation",
            "alternate_locations": "blank-then-A-otherwise-reject",
            "chain_breaks": "canonical-TER-per-input-segment",
            "multi_model": "reject",
        },
        "extract_sequence": {
            "name": "ca-residue-correspondent-sequence-extraction",
            "protein_records": "ATOM-only",
            "non_protein_records": "ignore-HETATM",
            "unknown_residue": "X",
            "chain_order": "PDB-segment-order",
            "residue_correspondence": "chain-qualified-residue-IDs",
            "alternate_locations": "blank-then-A-otherwise-reject",
            "multi_model": "reject",
        },
        "backbone_to_structure": {
            "name": "explicit-backbone-to-generic-structure-conversion",
            "input_contract": (
                "structure_transform.backbone_structure@2.1.0"
            ),
            "output_contract": "protein.structure@2.1.0",
            "pdb_bytes": "preserved",
            "atom_generation": "none",
        },
    }[operation]
    return MethodDefinition(
        method_id=f"structure_transform.{operation}.method",
        version=_VERSION,
        algorithm_identity=algorithm_identity,
        model_identity={"kind": "none"},
        checkpoint_identity={"kind": "none"},
        featurization_identity={
            "format": "PDB-v3.3-fixed-columns",
            "coordinates": "provider-native-decimal-text",
        },
        source_identity={"kind": "repository-owned"},
        scale_contract={"kind": "identity"},
    )


def _binding(operation: str) -> ExecutionBindingDefinition:
    return ExecutionBindingDefinition(
        binding_id=f"structure_transform.{operation}.direct",
        version=_VERSION,
        node_type=ContractIdentity(
            "node_type",
            f"structure_transform.{operation}",
            _VERSION,
        ),
        method=ContractIdentity(
            "method",
            f"structure_transform.{operation}.method",
            _VERSION,
        ),
        binding_parameters={},
        execution_route="direct",
        factory=LazyImplementationFactory(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/factory",
                _VERSION,
                {"execution_route": "direct"},
            ),
            build=_build(operation),
        ),
        availability=AvailabilityDeclaration(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/availability",
                _VERSION,
                {"observation": "startup"},
            ),
            prerequisites={},
            check=_available,
        ),
        readiness=ReadinessDeclaration(
            behavior=BehaviorReference(
                f"structure_transform.{operation}/readiness",
                _VERSION,
                {"observation": "per-run"},
            ),
            prerequisites={},
            check=_ready,
        ),
        deterministic=True,
        cacheable=True,
        implementation_identity={
            "name": f"structure_transform.{operation}.direct",
            "source": "repository-owned",
        },
    )


def _backbone_to_wire(value: object) -> object:
    assert type(value) is ProteinStructure
    return {
        "pdb_string": value.pdb_string,
        "source": value.source,
    }


def _backbone_from_wire(value: object) -> object:
    if (
        not isinstance(value, dict)
        or set(value) != {"pdb_string", "source"}
        or type(value["pdb_string"]) is not str
        or type(value["source"]) is not str
    ):
        raise ValueError("backbone wire value is invalid")
    return ProteinStructure(
        pdb_string=value["pdb_string"],
        source=value["source"],
    )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="structure_transform",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/select_chains.yaml"),
        DefinitionResource("definitions/extract_backbone.yaml"),
        DefinitionResource("definitions/extract_sequence.yaml"),
        DefinitionResource("definitions/backbone_to_structure.yaml"),
    ),
    methods=tuple(_method(operation) for operation in _OPERATIONS),
    bindings=tuple(_binding(operation) for operation in _OPERATIONS),
    port_types=(
        PortTypeDefinition(
            type_id="structure_transform.backbone_structure",
            version=_VERSION,
            validator=BehaviorReference(
                "structure_transform.backbone_structure/validate",
                _VERSION,
                {
                    "accepted_value_kind": "protein_structure",
                    "record_contract": {
                        "records": ["ATOM", "TER", "END"],
                        "atoms": ["N", "CA", "C", "O"],
                        "alternate_locations": "resolved",
                        "missing_atoms": "rejected",
                        "chain_breaks": "TER-terminated",
                    },
                },
            ),
            codec=BehaviorReference(
                "structure_transform.backbone_structure/codec",
                _VERSION,
                {
                    "canonicalization": "RFC 8785",
                    "pdb_line_endings": "LF",
                },
            ),
            content_identity=BehaviorReference(
                "structure_transform.backbone_structure/content",
                _VERSION,
                {"digest": "SHA-256"},
            ),
            runtime_validator=validate_backbone_structure,
            runtime_to_wire=_backbone_to_wire,
            runtime_from_wire=_backbone_from_wire,
        ),
    ),
)
