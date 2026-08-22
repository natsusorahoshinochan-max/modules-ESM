"""Canonical codec for resolved structure residue axes."""

from __future__ import annotations

import json
from math import isfinite

from core.catalog.builtins import builtin_frozen_catalog
from core.catalog.port_contract import (
    BehaviorReference,
    PortTypeDefinition,
    canonical_json_bytes,
)
from datatypes.structure import (
    ResolvedStructureResidueAxis,
    StructureAtomCoordinate,
    StructureAxisSegment,
    StructureComponentDisposition,
    StructureResidueCoordinates,
)

from ._normalization_codec import (
    NORMALIZATION_VERSION,
    normalizations_from_wire,
    normalizations_to_wire,
    validate_normalizations,
)


RESOLVED_AXIS_VERSION = "4.0.0"
_BUILTINS = builtin_frozen_catalog()
_STRUCTURE_CODEC = _BUILTINS.require_port_type(
    "protein.structure",
    "4.0.0",
)
_LAYOUT_CODEC = _BUILTINS.require_port_type("residue.layout", "3.0.0")
_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYX")
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


def _axis_from_wire(value: object) -> ResolvedStructureResidueAxis:
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

    return ResolvedStructureResidueAxis(
        structure=_decode_value(_STRUCTURE_CODEC, decoded["structure"]),
        layout=_decode_value(_LAYOUT_CODEC, decoded["layout"]),
        sequence=decoded["sequence"],
        residue_names=tuple(decoded["residue_names"]),
        segments=tuple(segments),
        component_dispositions=tuple(dispositions),
        modified_residue_normalizations=normalizations_from_wire(
            decoded["modified_residue_normalizations"]
        ),
        residue_coordinates=tuple(residue_coordinates),
        ca_coordinate_mask=tuple(decoded["ca_coordinate_mask"]),
        complete_backbone_mask=tuple(decoded["complete_backbone_mask"]),
    )


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
                f"{NORMALIZATION_VERSION}"
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
