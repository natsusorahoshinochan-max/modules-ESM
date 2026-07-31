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
from datatypes import (
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    ProteinStructure,
)

from .implementation import (
    StructureTransformImplementation,
    validate_backbone_structure,
)


_VERSION = "2.1.0"
_OPERATIONS = (
    "select_chains",
    "select_candidate_chains",
    "extract_backbone",
    "extract_sequence",
    "extract_sequence_candidates",
    "normalize_csh_parent_span",
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
        "select_candidate_chains": {
            "name": "candidate-aware-ordered-pdb-chain-selection",
            "selection": "ordered-exact-pdb-chain-selection",
            "cardinality": "one-child-per-input-parent",
            "lineage": "structure-parent-to-structure-child",
            "ordering": "input-candidate-order",
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
        "extract_sequence_candidates": {
            "name": "candidate-aware-sequence-extraction",
            "extraction": (
                "ca-residue-correspondent-sequence-extraction"
            ),
            "cardinality": "one-child-per-input-parent",
            "lineage": "structure-parent-to-sequence-child",
            "ordering": "input-candidate-order",
        },
        "normalize_csh_parent_span": {
            "name": "explicit-CSH-to-SHG-parent-span-normalization",
            "component": "CSH",
            "parent_residues": ["SER", "HIS", "GLY"],
            "parent_numbering": ["observed-1", "observed", "observed+1"],
            "atom_mapping": "closed-exact-19-atom-map",
            "provenance": "typed-normalization-output",
            "missing_or_extra_atoms": "reject",
            "identity_collision": "reject",
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


def _normalizations_to_wire(value: object) -> object:
    assert type(value) is ModifiedResidueNormalizationCollection
    return {
        "entries": [
            {
                "component_id": entry.component_id,
                "observed_residue_id": entry.observed_residue_id,
                "parent_residue_ids": list(entry.parent_residue_ids),
                "parent_sequence": entry.parent_sequence,
                "atom_mappings": [
                    {
                        "source_atom_name": mapping.source_atom_name,
                        "parent_residue_id": mapping.parent_residue_id,
                        "parent_atom_name": mapping.parent_atom_name,
                    }
                    for mapping in entry.atom_mappings
                ],
            }
            for entry in value.entries
        ]
    }


def _normalizations_from_wire(value: object) -> object:
    if not isinstance(value, dict) or set(value) != {"entries"}:
        raise ValueError("modified-residue normalization wire value is invalid")
    entries = value["entries"]
    if not isinstance(entries, list):
        raise ValueError("modified-residue normalization entries are invalid")
    decoded: list[ModifiedResidueNormalization] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "component_id",
            "observed_residue_id",
            "parent_residue_ids",
            "parent_sequence",
            "atom_mappings",
        }:
            raise ValueError("modified-residue normalization entry is invalid")
        mappings = entry["atom_mappings"]
        if (
            type(entry["component_id"]) is not str
            or type(entry["observed_residue_id"]) is not str
            or not isinstance(entry["parent_residue_ids"], list)
            or any(
                type(parent_id) is not str
                for parent_id in entry["parent_residue_ids"]
            )
            or type(entry["parent_sequence"]) is not str
            or not isinstance(mappings, list)
        ):
            raise ValueError("modified-residue atom mappings are invalid")
        decoded_mappings: list[ModifiedResidueAtomMapping] = []
        for mapping in mappings:
            if (
                not isinstance(mapping, dict)
                or set(mapping) != {
                    "source_atom_name",
                    "parent_residue_id",
                    "parent_atom_name",
                }
                or any(type(item) is not str for item in mapping.values())
            ):
                raise ValueError("modified-residue atom mapping is invalid")
            decoded_mappings.append(ModifiedResidueAtomMapping(**mapping))
        decoded.append(
            ModifiedResidueNormalization(
                component_id=entry["component_id"],
                observed_residue_id=entry["observed_residue_id"],
                parent_residue_ids=tuple(entry["parent_residue_ids"]),
                parent_sequence=entry["parent_sequence"],
                atom_mappings=tuple(decoded_mappings),
            )
        )
    result = ModifiedResidueNormalizationCollection(entries=decoded)
    _validate_normalizations(result)
    return result


def _validate_normalizations(value: object) -> None:
    if (
        type(value) is not ModifiedResidueNormalizationCollection
        or not value.entries
    ):
        raise ValueError(
            "modified-residue normalizations must be a nonempty collection"
        )
    observed_ids: set[str] = set()
    for entry in value.entries:
        if (
            type(entry) is not ModifiedResidueNormalization
            or not entry.component_id
            or not entry.observed_residue_id
            or not entry.parent_residue_ids
            or len(entry.parent_sequence) != len(entry.parent_residue_ids)
            or not entry.atom_mappings
            or entry.observed_residue_id in observed_ids
        ):
            raise ValueError("modified-residue normalization entry is invalid")
        observed_ids.add(entry.observed_residue_id)
        parent_ids = set(entry.parent_residue_ids)
        if len(parent_ids) != len(entry.parent_residue_ids):
            raise ValueError("modified-residue parent identities are duplicated")
        source_atoms: set[str] = set()
        covered_parents: set[str] = set()
        for mapping in entry.atom_mappings:
            if (
                type(mapping) is not ModifiedResidueAtomMapping
                or not mapping.source_atom_name
                or mapping.parent_residue_id not in parent_ids
                or not mapping.parent_atom_name
                or mapping.source_atom_name in source_atoms
            ):
                raise ValueError("modified-residue atom mapping is invalid")
            source_atoms.add(mapping.source_atom_name)
            covered_parents.add(mapping.parent_residue_id)
        if covered_parents != parent_ids:
            raise ValueError(
                "modified-residue atom mapping must cover every parent"
            )


MODULE_PACKAGE = ModulePackageRegistration(
    schema_version="2.1.0",
    package_id="structure_transform",
    package_version=_VERSION,
    package_module=__package__,
    node_definitions=(
        DefinitionResource("definitions/select_chains.yaml"),
        DefinitionResource("definitions/select_candidate_chains.yaml"),
        DefinitionResource("definitions/extract_backbone.yaml"),
        DefinitionResource("definitions/extract_sequence.yaml"),
        DefinitionResource("definitions/extract_sequence_candidates.yaml"),
        DefinitionResource("definitions/normalize_csh_parent_span.yaml"),
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
        PortTypeDefinition(
            type_id="structure_transform.modified_residue_normalizations",
            version=_VERSION,
            validator=BehaviorReference(
                "structure_transform.modified_residue_normalizations/validate",
                _VERSION,
                {
                    "accepted_value_kind": (
                        "modified_residue_normalization_collection"
                    ),
                    "provenance": "component-parent-atom-map",
                },
            ),
            codec=BehaviorReference(
                "structure_transform.modified_residue_normalizations/codec",
                _VERSION,
                {"canonicalization": "RFC 8785"},
            ),
            content_identity=BehaviorReference(
                "structure_transform.modified_residue_normalizations/content",
                _VERSION,
                {"digest": "SHA-256"},
            ),
            runtime_validator=_validate_normalizations,
            runtime_to_wire=_normalizations_to_wire,
            runtime_from_wire=_normalizations_from_wire,
        ),
    ),
)
