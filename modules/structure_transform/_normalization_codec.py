"""Canonical codec for modified-residue normalization evidence."""

from __future__ import annotations

from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from datatypes.residue import (
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    residue_identity_chain,
)


NORMALIZATION_VERSION = "3.0.0"
_PARENT_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWY")


def validate_normalizations(
    value: object,
    *,
    require_nonempty: bool = True,
) -> None:
    """Validate exact modified-component parent and atom correspondence."""
    if type(value) is not ModifiedResidueNormalizationCollection:
        raise ValueError(
            "modified-residue normalizations must be a collection"
        )
    if require_nonempty and not value.entries:
        raise ValueError(
            "modified-residue normalizations must be a nonempty collection"
        )
    observed_ids: set[str] = set()
    for entry in value.entries:
        if (
            type(entry) is not ModifiedResidueNormalization
            or type(entry.component_id) is not str
            or not 1 <= len(entry.component_id) <= 3
            or not entry.component_id.isascii()
            or not entry.component_id.isalnum()
            or entry.component_id != entry.component_id.upper()
            or type(entry.observed_residue_id) is not str
            or not entry.observed_residue_id
            or not entry.parent_residue_ids
            or type(entry.parent_sequence) is not str
            or len(entry.parent_sequence) != len(entry.parent_residue_ids)
            or any(
                letter not in _PARENT_SEQUENCE_ALPHABET
                for letter in entry.parent_sequence
            )
            or not entry.atom_mappings
            or entry.observed_residue_id in observed_ids
        ):
            raise ValueError("modified-residue normalization entry is invalid")
        residue_identity_chain(
            entry.observed_residue_id,
            subject="modified-residue observed identity",
        )
        observed_ids.add(entry.observed_residue_id)
        parent_ids = set(entry.parent_residue_ids)
        if (
            len(parent_ids) != len(entry.parent_residue_ids)
            or any(type(parent_id) is not str for parent_id in parent_ids)
        ):
            raise ValueError("modified-residue parent identities are invalid")
        for parent_id in parent_ids:
            residue_identity_chain(
                parent_id,
                subject="modified-residue parent identity",
            )
        source_atoms: set[str] = set()
        target_atoms: set[tuple[str, str]] = set()
        covered_parents: set[str] = set()
        for mapping in entry.atom_mappings:
            if type(mapping) is not ModifiedResidueAtomMapping:
                raise ValueError("modified-residue atom mapping is invalid")
            if (
                type(mapping.source_atom_name) is not str
                or not 1 <= len(mapping.source_atom_name) <= 4
                or mapping.source_atom_name.strip()
                != mapping.source_atom_name
                or any(
                    character.isspace()
                    for character in mapping.source_atom_name
                )
                or mapping.parent_residue_id not in parent_ids
                or type(mapping.parent_atom_name) is not str
                or not 1 <= len(mapping.parent_atom_name) <= 4
                or mapping.parent_atom_name.strip()
                != mapping.parent_atom_name
                or any(
                    character.isspace()
                    for character in mapping.parent_atom_name
                )
                or mapping.source_atom_name in source_atoms
            ):
                raise ValueError("modified-residue atom mapping is invalid")
            target_atom = (
                mapping.parent_residue_id,
                mapping.parent_atom_name,
            )
            if target_atom in target_atoms:
                raise ValueError("modified-residue atom mapping is invalid")
            source_atoms.add(mapping.source_atom_name)
            target_atoms.add(target_atom)
            covered_parents.add(mapping.parent_residue_id)
        if covered_parents != parent_ids:
            raise ValueError(
                "modified-residue atom mapping must cover every parent"
            )


def normalizations_to_wire(value: object) -> object:
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


def normalizations_from_wire(
    value: object,
) -> ModifiedResidueNormalizationCollection:
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
    return ModifiedResidueNormalizationCollection(entries=decoded)


MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.modified_residue_normalizations",
    version=NORMALIZATION_VERSION,
    validator=BehaviorReference(
        "structure_transform.modified_residue_normalizations/validate",
        NORMALIZATION_VERSION,
        {
            "accepted_value_kind": (
                "modified_residue_normalization_collection"
            ),
            "provenance": "component-parent-atom-map",
            "parent_sequence": "20-standard-amino-acid-alphabet",
            "atom_mapping": "unique-source-and-parent-target-atoms",
        },
    ),
    codec=BehaviorReference(
        "structure_transform.modified_residue_normalizations/codec",
        NORMALIZATION_VERSION,
        {"canonicalization": "RFC 8785"},
    ),
    content_identity=BehaviorReference(
        "structure_transform.modified_residue_normalizations/content",
        NORMALIZATION_VERSION,
        {"digest": "SHA-256"},
    ),
    runtime_validator=validate_normalizations,
    runtime_to_wire=normalizations_to_wire,
    runtime_from_wire=normalizations_from_wire,
)
