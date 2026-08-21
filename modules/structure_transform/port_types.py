"""Nominal Port Types owned by the structure-transform package."""

from __future__ import annotations

import json
from math import isfinite
from typing import Any, cast

from core import BehaviorReference, PortTypeDefinition, builtin_frozen_catalog
from core.port_types import canonical_json_bytes
from datatypes import (
    CandidateDataReference,
    ExactContractReference,
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    ResidueAxisReference,
    ResolvedStructureResidueAxis,
    StructureAtomCoordinate,
    StructureAxisSegment,
    StructureComponentDisposition,
    StructureResidueCoordinates,
)
from datatypes.protein import residue_identity_chain

from .domain import (
    CandidateNormalizationFact,
    CandidateNormalizationFactCollection,
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)


RESOLVED_AXIS_VERSION = "4.0.0"
CANDIDATE_ASSOCIATION_VERSION = "6.0.0"
NORMALIZATION_FACTS_VERSION = "1.0.0"
_NORMALIZATION_VERSION = "3.0.0"
_BUILTINS = builtin_frozen_catalog()
_STRUCTURE_CODEC = _BUILTINS.require_port_type(
    "protein.structure",
    "4.0.0",
)
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout", "3.0.0")
_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYX")
_PARENT_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWY")
_BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O"})
_RESIDUE_LETTERS = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def _wire_value(codec: PortTypeDefinition, value: object) -> object:
    return json.loads(codec.encode(value))["value"]


def _decode_value(
    codec: PortTypeDefinition,
    wire_value: object,
) -> object:
    return codec.decode(
        canonical_json_bytes(
            {
                "schema_namespace": "protein-workbench-port-value/v2",
                "port_type_id": codec.type_id,
                "port_type_version": codec.version,
                "value": wire_value,
            }
        )
    )


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
    *,
    require_nonempty: bool = True,
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
    result = ModifiedResidueNormalizationCollection(entries=decoded)
    validate_normalizations(result, require_nonempty=require_nonempty)
    return result


MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.modified_residue_normalizations",
    version=_NORMALIZATION_VERSION,
    validator=BehaviorReference(
        "structure_transform.modified_residue_normalizations/validate",
        _NORMALIZATION_VERSION,
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
        _NORMALIZATION_VERSION,
        {"canonicalization": "RFC 8785"},
    ),
    content_identity=BehaviorReference(
        "structure_transform.modified_residue_normalizations/content",
        _NORMALIZATION_VERSION,
        {"digest": "SHA-256"},
    ),
    runtime_validator=validate_normalizations,
    runtime_to_wire=normalizations_to_wire,
    runtime_from_wire=normalizations_from_wire,
)


def _validate_residue_coordinates(
    value: object,
    *,
    expected_residue_id: str,
) -> tuple[set[str], StructureResidueCoordinates]:
    if (
        type(value) is not StructureResidueCoordinates
        or value.residue_id != expected_residue_id
        or not value.atom_coordinates
    ):
        raise ValueError("resolved-axis residue coordinates are misaligned")
    atom_names: set[str] = set()
    for atom in value.atom_coordinates:
        if (
            type(atom) is not StructureAtomCoordinate
            or type(atom.atom_name) is not str
            or not atom.atom_name
            or atom.atom_name.strip() != atom.atom_name
            or any(character.isspace() for character in atom.atom_name)
            or atom.atom_name in atom_names
            or len(atom.coordinate) != 3
            or any(
                type(coordinate) not in (int, float)
                or not isfinite(coordinate)
                for coordinate in atom.coordinate
            )
        ):
            raise ValueError("resolved-axis atom coordinate is invalid")
        atom_names.add(atom.atom_name)
    return atom_names, value


def _validate_component_disposition(
    value: object,
    *,
    axis_sequence: dict[str, str],
) -> None:
    if (
        type(value) is not StructureComponentDisposition
        or type(value.component_id) is not str
        or not value.component_id
        or type(value.observed_residue_id) is not str
        or not value.observed_residue_id
        or value.record_type not in {"ATOM", "HETATM"}
    ):
        raise ValueError("resolved-axis component disposition is invalid")
    allowed = {
        ("polymer", "included", None),
        ("modified_polymer", "normalized", "pdb_modres"),
        ("modified_polymer", "normalized", "explicit_mapping"),
        ("ligand", "excluded", None),
        ("water", "excluded", None),
    }
    if (
        value.component_role,
        value.disposition,
        value.normalization_source,
    ) not in allowed:
        raise ValueError("resolved-axis component disposition is inconsistent")
    if value.disposition == "excluded":
        if (
            value.parent_residue_ids
            or value.parent_sequence
            or value.observed_residue_id in axis_sequence
        ):
            raise ValueError("excluded components cannot claim axis parents")
        return
    if (
        not value.parent_residue_ids
        or len(value.parent_residue_ids) != len(value.parent_sequence)
        or any(
            parent_id not in axis_sequence
            for parent_id in value.parent_residue_ids
        )
        or any(letter not in _SEQUENCE_ALPHABET for letter in value.parent_sequence)
        or any(
            axis_sequence[parent_id] != letter
            for parent_id, letter in zip(
                value.parent_residue_ids,
                value.parent_sequence,
                strict=True,
            )
        )
    ):
        raise ValueError("admitted component axis parents are invalid")
    if value.component_role == "polymer" and (
        value.parent_residue_ids != (value.observed_residue_id,)
        or len(value.parent_sequence) != 1
    ):
        raise ValueError("standard polymer disposition must own one identity")
    if value.normalization_source == "pdb_modres" and (
        value.parent_residue_ids != (value.observed_residue_id,)
        or len(value.parent_sequence) != 1
    ):
        raise ValueError("same-identity MODRES normalization is invalid")


def _normalization_identity(
    component_id: str,
    observed_residue_id: str,
    parent_residue_ids: tuple[str, ...],
    parent_sequence: str,
) -> tuple[str, str, tuple[str, ...], str]:
    return (
        component_id,
        observed_residue_id,
        tuple(parent_residue_ids),
        parent_sequence,
    )


def validate_resolved_axis(value: object) -> None:
    """Validate one complete, topology-preserving structure residue axis."""
    if type(value) is not ResolvedStructureResidueAxis:
        raise ValueError(
            "resolved residue axis must be a ResolvedStructureResidueAxis"
        )
    _STRUCTURE_CODEC.validate(value.structure)
    _LAYOUT_CODEC.validate(value.layout)
    residue_ids = value.layout.residue_ids
    if residue_ids is None:
        raise ValueError("resolved residue axis layout lacks identities")
    axis_length = value.layout.length
    if (
        type(value.sequence) is not str
        or len(value.sequence) != axis_length
        or any(letter not in _SEQUENCE_ALPHABET for letter in value.sequence)
        or len(value.residue_names) != axis_length
        or any(
            type(residue_name) is not str or not residue_name
            for residue_name in value.residue_names
        )
        or len(value.residue_coordinates) != axis_length
        or len(value.ca_coordinate_mask) != axis_length
        or len(value.complete_backbone_mask) != axis_length
        or any(type(item) is not bool for item in value.ca_coordinate_mask)
        or any(
            type(item) is not bool for item in value.complete_backbone_mask
        )
    ):
        raise ValueError("resolved residue axis fields do not match its layout")
    for residue_name, letter in zip(
        value.residue_names,
        value.sequence,
        strict=True,
    ):
        expected_letter = _RESIDUE_LETTERS.get(residue_name, "X")
        if letter != expected_letter:
            raise ValueError(
                "resolved residue name contradicts its sequence letter"
            )

    if not value.segments:
        raise ValueError("resolved residue axis must declare segment topology")
    flattened_segment_ids: list[str] = []
    for index, segment in enumerate(value.segments):
        if (
            type(segment) is not StructureAxisSegment
            or type(segment.segment_index) is not int
            or segment.segment_index != index
            or type(segment.chain_id) is not str
            or len(segment.chain_id) != 1
            or not segment.chain_id.isascii()
            or not segment.chain_id.isalnum()
            or not segment.residue_ids
            or any(
                residue_id.split(":", 1)[0] != segment.chain_id
                for residue_id in segment.residue_ids
            )
        ):
            raise ValueError("resolved residue axis segment is invalid")
        flattened_segment_ids.extend(segment.residue_ids)
    if tuple(flattened_segment_ids) != tuple(residue_ids):
        raise ValueError(
            "resolved residue axis segments do not partition its layout"
        )

    derived_ca_mask: list[bool] = []
    derived_backbone_mask: list[bool] = []
    coordinate_atoms_by_residue: dict[str, set[str]] = {}
    for residue_id, coordinates in zip(
        residue_ids,
        value.residue_coordinates,
        strict=True,
    ):
        atom_names, _ = _validate_residue_coordinates(
            coordinates,
            expected_residue_id=residue_id,
        )
        derived_ca_mask.append("CA" in atom_names)
        derived_backbone_mask.append(_BACKBONE_ATOMS <= atom_names)
        coordinate_atoms_by_residue[residue_id] = atom_names
    if (
        tuple(derived_ca_mask) != value.ca_coordinate_mask
        or tuple(derived_backbone_mask) != value.complete_backbone_mask
    ):
        raise ValueError("resolved residue axis coordinate masks are incorrect")

    if not value.component_dispositions:
        raise ValueError("resolved residue axis requires component dispositions")
    disposition_ids: set[tuple[str, str]] = set()
    covered_axis_ids: set[str] = set()
    axis_sequence = dict(zip(residue_ids, value.sequence, strict=True))
    for disposition in value.component_dispositions:
        _validate_component_disposition(
            disposition,
            axis_sequence=axis_sequence,
        )
        identity = (disposition.component_id, disposition.observed_residue_id)
        if identity in disposition_ids:
            raise ValueError("resolved-axis component disposition is duplicated")
        disposition_ids.add(identity)
        if disposition.disposition != "excluded":
            covered_axis_ids.update(disposition.parent_residue_ids)
    if covered_axis_ids != set(axis_sequence):
        raise ValueError(
            "resolved-axis component dispositions do not cover its layout"
        )

    validate_normalizations(
        value.modified_residue_normalizations,
        require_nonempty=False,
    )
    normalization_identities = {
        _normalization_identity(
            normalization.component_id,
            normalization.observed_residue_id,
            normalization.parent_residue_ids,
            normalization.parent_sequence,
        )
        for normalization in value.modified_residue_normalizations.entries
    }
    disposition_normalization_identities = {
        _normalization_identity(
            disposition.component_id,
            disposition.observed_residue_id,
            disposition.parent_residue_ids,
            disposition.parent_sequence,
        )
        for disposition in value.component_dispositions
        if disposition.component_role == "modified_polymer"
        and disposition.disposition == "normalized"
    }
    if normalization_identities != disposition_normalization_identities:
        raise ValueError(
            "normalized component dispositions and mappings are not closed"
        )
    for normalization in value.modified_residue_normalizations.entries:
        for parent_id, letter in zip(
            normalization.parent_residue_ids,
            normalization.parent_sequence,
            strict=True,
        ):
            if axis_sequence.get(parent_id) != letter:
                raise ValueError(
                    "modified-residue normalization contradicts axis sequence"
                )
        if any(
            mapping.parent_atom_name
            not in coordinate_atoms_by_residue[mapping.parent_residue_id]
            for mapping in normalization.atom_mappings
        ):
            raise ValueError(
                "modified-residue normalization points outside axis coordinates"
            )
        if not any(
            disposition.component_id == normalization.component_id
            and disposition.observed_residue_id
            == normalization.observed_residue_id
            and disposition.component_role == "modified_polymer"
            and disposition.disposition == "normalized"
            and disposition.parent_residue_ids
            == normalization.parent_residue_ids
            and disposition.parent_sequence == normalization.parent_sequence
            for disposition in value.component_dispositions
        ):
            raise ValueError(
                "modified-residue normalization lacks a matching disposition"
            )

def _axis_to_wire(value: object) -> object:
    assert type(value) is ResolvedStructureResidueAxis
    return {
        "structure": _wire_value(_STRUCTURE_CODEC, value.structure),
        "layout": _wire_value(_LAYOUT_CODEC, value.layout),
        "sequence": value.sequence,
        "residue_names": list(value.residue_names),
        "segments": [
            {
                "segment_index": segment.segment_index,
                "chain_id": segment.chain_id,
                "residue_ids": list(segment.residue_ids),
            }
            for segment in value.segments
        ],
        "component_dispositions": [
            {
                "component_id": item.component_id,
                "observed_residue_id": item.observed_residue_id,
                "record_type": item.record_type,
                "component_role": item.component_role,
                "disposition": item.disposition,
                "parent_residue_ids": list(item.parent_residue_ids),
                "parent_sequence": item.parent_sequence,
                "normalization_source": item.normalization_source,
            }
            for item in value.component_dispositions
        ],
        "modified_residue_normalizations": normalizations_to_wire(
            value.modified_residue_normalizations
        ),
        "residue_coordinates": [
            {
                "residue_id": item.residue_id,
                "atom_coordinates": [
                    {
                        "atom_name": atom.atom_name,
                        "coordinate": list(atom.coordinate),
                    }
                    for atom in item.atom_coordinates
                ],
            }
            for item in value.residue_coordinates
        ],
        "ca_coordinate_mask": list(value.ca_coordinate_mask),
        "complete_backbone_mask": list(value.complete_backbone_mask),
    }


def _closed_dict(
    value: object,
    fields: set[str],
    *,
    subject: str,
) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{subject} is not a closed object")
    return value


def _axis_from_wire(value: object) -> object:
    decoded = _closed_dict(
        value,
        {
            "structure",
            "layout",
            "sequence",
            "residue_names",
            "segments",
            "component_dispositions",
            "modified_residue_normalizations",
            "residue_coordinates",
            "ca_coordinate_mask",
            "complete_backbone_mask",
        },
        subject="resolved residue axis",
    )
    list_fields = (
        "residue_names",
        "segments",
        "component_dispositions",
        "residue_coordinates",
        "ca_coordinate_mask",
        "complete_backbone_mask",
    )
    if (
        type(decoded["sequence"]) is not str
        or any(not isinstance(decoded[field], list) for field in list_fields)
    ):
        raise ValueError("resolved residue axis wire fields are invalid")

    segments: list[StructureAxisSegment] = []
    for item in decoded["segments"]:
        item = _closed_dict(
            item,
            {"segment_index", "chain_id", "residue_ids"},
            subject="resolved residue axis segment",
        )
        if (
            type(item["segment_index"]) is not int
            or type(item["chain_id"]) is not str
            or not isinstance(item["residue_ids"], list)
            or any(type(residue_id) is not str for residue_id in item["residue_ids"])
        ):
            raise ValueError("resolved residue axis segment fields are invalid")
        segments.append(
            StructureAxisSegment(
                segment_index=item["segment_index"],
                chain_id=item["chain_id"],
                residue_ids=tuple(item["residue_ids"]),
            )
        )

    dispositions: list[StructureComponentDisposition] = []
    for item in decoded["component_dispositions"]:
        item = _closed_dict(
            item,
            {
                "component_id",
                "observed_residue_id",
                "record_type",
                "component_role",
                "disposition",
                "parent_residue_ids",
                "parent_sequence",
                "normalization_source",
            },
            subject="resolved residue axis component disposition",
        )
        if (
            any(
                type(item[field]) is not str
                for field in (
                    "component_id",
                    "observed_residue_id",
                    "record_type",
                    "component_role",
                    "disposition",
                    "parent_sequence",
                )
            )
            or item["normalization_source"] is not None
            and type(item["normalization_source"]) is not str
            or not isinstance(item["parent_residue_ids"], list)
            or any(
                type(parent_id) is not str
                for parent_id in item["parent_residue_ids"]
            )
        ):
            raise ValueError(
                "resolved residue axis component disposition fields are invalid"
            )
        dispositions.append(
            StructureComponentDisposition(
                component_id=item["component_id"],
                observed_residue_id=item["observed_residue_id"],
                record_type=item["record_type"],
                component_role=item["component_role"],
                disposition=item["disposition"],
                parent_residue_ids=tuple(item["parent_residue_ids"]),
                parent_sequence=item["parent_sequence"],
                normalization_source=item["normalization_source"],
            )
        )

    residue_coordinates: list[StructureResidueCoordinates] = []
    for item in decoded["residue_coordinates"]:
        item = _closed_dict(
            item,
            {"residue_id", "atom_coordinates"},
            subject="resolved residue axis residue coordinates",
        )
        if (
            type(item["residue_id"]) is not str
            or not isinstance(item["atom_coordinates"], list)
        ):
            raise ValueError("resolved residue coordinate fields are invalid")
        atoms: list[StructureAtomCoordinate] = []
        for atom in item["atom_coordinates"]:
            atom = _closed_dict(
                atom,
                {"atom_name", "coordinate"},
                subject="resolved residue axis atom coordinate",
            )
            if (
                type(atom["atom_name"]) is not str
                or not isinstance(atom["coordinate"], list)
                or len(atom["coordinate"]) != 3
                or any(
                    type(coordinate) not in (int, float)
                    for coordinate in atom["coordinate"]
                )
            ):
                raise ValueError("resolved residue atom coordinate fields are invalid")
            atoms.append(
                StructureAtomCoordinate(
                    atom_name=atom["atom_name"],
                    coordinate=tuple(atom["coordinate"]),
                )
            )
        residue_coordinates.append(
            StructureResidueCoordinates(
                residue_id=item["residue_id"],
                atom_coordinates=tuple(atoms),
            )
        )

    result = ResolvedStructureResidueAxis(
        structure=_decode_value(_STRUCTURE_CODEC, decoded["structure"]),
        layout=_decode_value(_LAYOUT_CODEC, decoded["layout"]),
        sequence=decoded["sequence"],
        residue_names=tuple(decoded["residue_names"]),
        segments=tuple(segments),
        component_dispositions=tuple(dispositions),
        modified_residue_normalizations=normalizations_from_wire(
            decoded["modified_residue_normalizations"],
            require_nonempty=False,
        ),
        residue_coordinates=tuple(residue_coordinates),
        ca_coordinate_mask=tuple(decoded["ca_coordinate_mask"]),
        complete_backbone_mask=tuple(decoded["complete_backbone_mask"]),
    )
    validate_resolved_axis(result)
    return result


RESOLVED_AXIS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.resolved_residue_axis",
    version=RESOLVED_AXIS_VERSION,
    validator=BehaviorReference(
        "structure_transform.resolved_residue_axis/validate",
        RESOLVED_AXIS_VERSION,
        {
            "accepted_value_kind": "resolved_structure_residue_axis",
            "layout": "identity-complete-admitted-polymer-residues",
            "component_dispositions": "all-observed-coordinate-components",
            "segment_topology": "explicit-ordered-TER-and-chain-segments",
            "coordinate_selection": "blank-altloc-then-A",
            "coordinate_masks": ["CA", "complete-N-CA-C-O"],
            "structure_binding": "canonical-resolver-reprojection",
        },
    ),
    codec=BehaviorReference(
        "structure_transform.resolved_residue_axis/codec",
        RESOLVED_AXIS_VERSION,
        {
            "canonicalization": "RFC 8785",
            "character_encoding": "UTF-8",
            "embedded_structure_contract": "protein.structure@4.0.0",
            "embedded_layout_contract": "residue.layout@3.0.0",
            "embedded_normalization_contract": (
                "structure_transform.modified_residue_normalizations@"
                f"{_NORMALIZATION_VERSION}"
            ),
        },
    ),
    content_identity=BehaviorReference(
        "structure_transform.resolved_residue_axis/content",
        RESOLVED_AXIS_VERSION,
        {
            "digest": "SHA-256",
            "digest_input": "canonical_codec_bytes",
        },
    ),
    runtime_validator=validate_resolved_axis,
    runtime_to_wire=_axis_to_wire,
    runtime_from_wire=_axis_from_wire,
)


def _validate_structure_subject(value: object) -> CandidateDataReference:
    if (
        type(value) is not CandidateDataReference
        or value.data_type_id != "protein.structure"
    ):
        raise ValueError(
            "Candidate association subject must be an exact protein.structure "
            "CandidateDataReference"
        )
    return value


def _validate_unique_candidate_subjects(
    subjects: tuple[CandidateDataReference, ...],
) -> None:
    if not subjects:
        raise ValueError("Candidate association collection must be nonempty")
    candidate_ids = [subject.candidate_id for subject in subjects]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError(
            "Candidate association collection contains a duplicate Candidate"
        )


def validate_candidate_normalization_associations(value: object) -> None:
    """Validate reference-addressed normalization sets without index pairing."""
    if type(value) is not CandidateModifiedResidueNormalizationAssociations:
        raise ValueError(
            "Candidate modified-residue normalizations have the wrong type"
        )
    subjects: list[CandidateDataReference] = []
    for entry in value.entries:
        if type(entry) is not CandidateModifiedResidueNormalizationAssociation:
            raise ValueError(
                "Candidate normalization association has the wrong type"
            )
        subjects.append(_validate_structure_subject(entry.subject))
        validate_normalizations(
            entry.normalizations,
            require_nonempty=False,
        )
    _validate_unique_candidate_subjects(tuple(subjects))


def _candidate_normalizations_to_wire(value: object) -> object:
    assert type(value) is CandidateModifiedResidueNormalizationAssociations
    return {
        "entries": [
            {
                "subject": entry.subject.to_public(),
                "normalizations": normalizations_to_wire(
                    entry.normalizations
                ),
            }
            for entry in value.entries
        ]
    }


def _candidate_normalizations_from_wire(value: object) -> object:
    decoded = _closed_dict(
        value,
        {"entries"},
        subject="Candidate normalization associations",
    )
    if not isinstance(decoded["entries"], list):
        raise ValueError(
            "Candidate normalization association entries must be a list"
        )
    entries: list[CandidateModifiedResidueNormalizationAssociation] = []
    for item in decoded["entries"]:
        item = _closed_dict(
            item,
            {"subject", "normalizations"},
            subject="Candidate normalization association",
        )
        entries.append(
            CandidateModifiedResidueNormalizationAssociation(
                subject=CandidateDataReference.from_public(item["subject"]),
                normalizations=normalizations_from_wire(
                    item["normalizations"],
                    require_nonempty=False,
                ),
            )
        )
    result = CandidateModifiedResidueNormalizationAssociations(
        entries=tuple(entries)
    )
    validate_candidate_normalization_associations(result)
    return result


def validate_candidate_resolved_axis_associations(value: object) -> None:
    """Validate axes against their exact Candidate structure references."""
    if type(value) is not CandidateResolvedResidueAxisAssociations:
        raise ValueError("Candidate resolved residue axes have the wrong type")
    subjects: list[CandidateDataReference] = []
    for entry in value.entries:
        if type(entry) is not CandidateResolvedResidueAxisAssociation:
            raise ValueError("Candidate residue-axis association has the wrong type")
        subject = _validate_structure_subject(entry.subject)
        validate_resolved_axis(entry.residue_axis)
        if (
            _STRUCTURE_CODEC.content_digest(entry.residue_axis.structure)
            != subject.content_digest
        ):
            raise ValueError(
                "Candidate residue axis contradicts its structure content digest"
            )
        subjects.append(subject)
    _validate_unique_candidate_subjects(tuple(subjects))


def _candidate_axes_to_wire(value: object) -> object:
    assert type(value) is CandidateResolvedResidueAxisAssociations
    return {
        "entries": [
            {
                "subject": entry.subject.to_public(),
                "residue_axis": _wire_value(
                    RESOLVED_AXIS_PORT_TYPE,
                    entry.residue_axis,
                ),
            }
            for entry in value.entries
        ]
    }


def _candidate_axes_from_wire(value: object) -> object:
    decoded = _closed_dict(
        value,
        {"entries"},
        subject="Candidate residue-axis associations",
    )
    if not isinstance(decoded["entries"], list):
        raise ValueError("Candidate residue-axis entries must be a list")
    entries: list[CandidateResolvedResidueAxisAssociation] = []
    for item in decoded["entries"]:
        item = _closed_dict(
            item,
            {"subject", "residue_axis"},
            subject="Candidate residue-axis association",
        )
        residue_axis = _decode_value(
            RESOLVED_AXIS_PORT_TYPE,
            item["residue_axis"],
        )
        if type(residue_axis) is not ResolvedStructureResidueAxis:
            raise ValueError("Candidate residue axis has the wrong runtime type")
        entries.append(
            CandidateResolvedResidueAxisAssociation(
                subject=CandidateDataReference.from_public(item["subject"]),
                residue_axis=residue_axis,
            )
        )
    return CandidateResolvedResidueAxisAssociations(entries=tuple(entries))


def _candidate_axis_references(
    value: object,
) -> tuple[ResidueAxisReference, ...]:
    """Project independently identified scalar axes from one association set."""
    admitted = cast(CandidateResolvedResidueAxisAssociations, value)
    reference = RESOLVED_AXIS_PORT_TYPE.reference()
    axis_contract = ExactContractReference(
        contract_kind=reference["contract_kind"],
        contract_id=reference["contract_id"],
        contract_version=reference["contract_version"],
        contract_digest=reference["contract_digest"],
    )
    return tuple(
        ResidueAxisReference(
            axis_kind="resolved_structure",
            axis_contract=axis_contract,
            axis_content_digest=RESOLVED_AXIS_PORT_TYPE.content_digest(
                entry.residue_axis
            ),
            source=entry.subject,
            layout=entry.residue_axis.layout,
        )
        for entry in admitted.entries
    )


def _association_candidate_data_references(
    value: object,
    _candidate_data_port_types: object,
) -> tuple[CandidateDataReference, ...]:
    admitted = cast(Any, value)
    return tuple(entry.subject for entry in admitted.entries)


def _validate_normalization_facts(value: object) -> None:
    if type(value) is not CandidateNormalizationFactCollection:
        raise ValueError("candidate normalization facts have the wrong type")
    for entry in value.entries:
        validate_normalizations(entry.normalizations)
    normalized = CandidateNormalizationFactCollection(value.entries)
    if normalized != value:
        raise ValueError("candidate normalization facts are not canonical")


def _normalization_facts_to_wire(value: object) -> object:
    assert type(value) is CandidateNormalizationFactCollection
    return {
        "entries": [
            {
                "normalization_key": entry.normalization_key,
                "structure_content_digest": entry.structure_content_digest,
                "normalizations": normalizations_to_wire(entry.normalizations),
            }
            for entry in value.entries
        ]
    }


def _normalization_facts_from_wire(value: object) -> object:
    decoded = _closed_dict(
        value,
        {"entries"},
        subject="candidate normalization facts",
    )
    if not isinstance(decoded["entries"], list):
        raise ValueError("candidate normalization fact entries must be a list")
    entries: list[CandidateNormalizationFact] = []
    for item in decoded["entries"]:
        item = _closed_dict(
            item,
            {
                "normalization_key",
                "structure_content_digest",
                "normalizations",
            },
            subject="candidate normalization fact",
        )
        if (
            type(item["normalization_key"]) is not str
            or type(item["structure_content_digest"]) is not str
        ):
            raise ValueError("candidate normalization fact fields are invalid")
        entries.append(
            CandidateNormalizationFact(
                normalization_key=item["normalization_key"],
                structure_content_digest=item["structure_content_digest"],
                normalizations=normalizations_from_wire(item["normalizations"]),
            )
        )
    keys = [entry.normalization_key for entry in entries]
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise ValueError(
            "candidate normalization fact entries are not canonically ordered"
        )
    result = CandidateNormalizationFactCollection(tuple(entries))
    _validate_normalization_facts(result)
    return result


CANDIDATE_NORMALIZATION_FACTS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.candidate_normalization_facts",
    version=NORMALIZATION_FACTS_VERSION,
    validator=BehaviorReference(
        "structure_transform.candidate_normalization_facts/validate",
        NORMALIZATION_FACTS_VERSION,
        {
            "accepted_value_kind": "candidate_normalization_fact_collection",
            "candidate_identity": "materialized-only-after-admission",
            "entry_key": "normalization_key",
        },
    ),
    codec=BehaviorReference(
        "structure_transform.candidate_normalization_facts/codec",
        NORMALIZATION_FACTS_VERSION,
        {"canonicalization": "RFC 8785", "entry_order": "normalization_key"},
    ),
    content_identity=BehaviorReference(
        "structure_transform.candidate_normalization_facts/content",
        NORMALIZATION_FACTS_VERSION,
        {"digest": "SHA-256", "digest_input": "canonical_codec_bytes"},
    ),
    runtime_validator=_validate_normalization_facts,
    runtime_to_wire=_normalization_facts_to_wire,
    runtime_from_wire=_normalization_facts_from_wire,
)


CANDIDATE_NORMALIZATION_ASSOCIATIONS_PORT_TYPE = PortTypeDefinition(
    type_id=(
        "structure_transform."
        "candidate_modified_residue_normalization_associations"
    ),
    version=CANDIDATE_ASSOCIATION_VERSION,
    validator=BehaviorReference(
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations/validate"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "accepted_value_kind": (
                "candidate_modified_residue_normalization_associations"
            ),
            "association_key": "exact-CandidateDataReference",
            "entry_order": "canonical-only-not-correspondence",
            "candidate_coverage": "closed-by-consuming-Node",
            "embedded_normalization_contract": (
                "structure_transform.modified_residue_normalizations@"
                f"{_NORMALIZATION_VERSION}"
            ),
        },
    ),
    codec=BehaviorReference(
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations/codec"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "canonicalization": "RFC 8785",
            "association_order": (
                "candidate-id-data-type-id-content-digest"
            ),
        },
    ),
    content_identity=BehaviorReference(
        (
            "structure_transform."
            "candidate_modified_residue_normalization_associations/content"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {"digest": "SHA-256", "digest_input": "canonical_codec_bytes"},
    ),
    runtime_validator=validate_candidate_normalization_associations,
    runtime_to_wire=_candidate_normalizations_to_wire,
    runtime_from_wire=_candidate_normalizations_from_wire,
    candidate_data_projection=BehaviorReference(
        "structure_transform.candidate_modified_residue_normalization_"
        "associations/candidate_data_projection",
        CANDIDATE_ASSOCIATION_VERSION,
        {"fields": ["entries[].subject"]},
    ),
    runtime_candidate_data_projection=(
        _association_candidate_data_references
    ),
)


CANDIDATE_RESOLVED_AXIS_ASSOCIATIONS_PORT_TYPE = PortTypeDefinition(
    type_id="structure_transform.candidate_resolved_residue_axis_associations",
    version=CANDIDATE_ASSOCIATION_VERSION,
    validator=BehaviorReference(
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations/validate"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "accepted_value_kind": "candidate_resolved_residue_axis_associations",
            "association_key": "exact-CandidateDataReference",
            "entry_order": "canonical-only-not-correspondence",
            "structure_binding": "subject-content-digest-equals-embedded-structure",
            "embedded_axis_contract": (
                "structure_transform.resolved_residue_axis@"
                f"{RESOLVED_AXIS_VERSION}"
            ),
        },
    ),
    codec=BehaviorReference(
        "structure_transform.candidate_resolved_residue_axis_associations/codec",
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "canonicalization": "RFC 8785",
            "association_order": (
                "candidate-id-data-type-id-content-digest"
            ),
        },
    ),
    content_identity=BehaviorReference(
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations/content"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {"digest": "SHA-256", "digest_input": "canonical_codec_bytes"},
    ),
    runtime_validator=validate_candidate_resolved_axis_associations,
    runtime_to_wire=_candidate_axes_to_wire,
    runtime_from_wire=_candidate_axes_from_wire,
    candidate_data_projection=BehaviorReference(
        "structure_transform.candidate_resolved_residue_axis_associations/"
        "candidate_data_projection",
        CANDIDATE_ASSOCIATION_VERSION,
        {"fields": ["entries[].subject"]},
    ),
    runtime_candidate_data_projection=(
        _association_candidate_data_references
    ),
    scientific_axis_projection=BehaviorReference(
        (
            "structure_transform."
            "candidate_resolved_residue_axis_associations/"
            "scientific_axis_projection"
        ),
        CANDIDATE_ASSOCIATION_VERSION,
        {
            "association_key": "exact-CandidateDataReference",
            "projected_axis_contract": (
                "structure_transform.resolved_residue_axis@"
                f"{RESOLVED_AXIS_VERSION}"
            ),
            "projected_axis_identity": "independent-scalar-codec-digest",
        },
    ),
    runtime_scientific_axis_projection=_candidate_axis_references,
)
