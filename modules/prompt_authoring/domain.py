"""Shared residue-layout and track invariants for prompt authoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Any, Literal, NotRequired, TypedDict

from datatypes import ResidueLayout, ResidueMap
from datatypes.protein import (
    residue_identity_chain,
    validate_residue_layout,
    validate_residue_map as validate_canonical_residue_map,
)


_SECONDARY_STRUCTURE = frozenset({"H", "B", "E", "G", "I", "T", "S", "-"})
_MAX_RESIDUES = 2_000_000


class TrackKind(Enum):
    """Closed scientific value domains supported by the track Nodes."""

    SEQUENCE = "sequence"
    STRUCTURE = "structure"
    VISIBILITY = "visibility"
    SECONDARY_STRUCTURE = "secondary_structure"
    SASA = "sasa"


@dataclass(frozen=True, slots=True)
class AlignedResidueTrack:
    """One nullable value per explicit residue identity in one layout."""

    layout: ResidueLayout
    values: tuple[Any, ...]


class ChainDeclaration(TypedDict):
    """One Plan-admitted chain declaration."""

    chain_id: str
    length: int


class ResidueEditDeclaration(TypedDict):
    """One Plan-admitted identity-addressed residue edit."""

    operation: Literal["insert", "delete"]
    chain_id: str
    residue_id: str


class TrackOverrideDeclaration(TypedDict):
    """One Plan-admitted identity-addressed track override."""

    action: Literal["clear", "preserve", "replace"]
    residue_id: str
    value: NotRequired[object]


def residue_chain(residue_id: str) -> str:
    """Return the chain encoded by one canonical residue identity."""
    return residue_identity_chain(residue_id)


def validate_layout(layout: object, *, subject: str) -> ResidueLayout:
    """Validate one identity-complete layout and its contiguous chains."""
    admitted = validate_residue_layout(layout, subject=subject)
    if admitted.length > _MAX_RESIDUES:
        raise ValueError(f"{subject} length is outside the supported range")
    return admitted


def build_layout(chains: Sequence[ChainDeclaration]) -> ResidueLayout:
    """Construct a canonical layout from ordered chain lengths."""
    chain_ids: list[str] = []
    residue_ids: list[str] = []
    for raw_chain in chains:
        chain_id = raw_chain["chain_id"]
        length = raw_chain["length"]
        if chain_id in chain_ids:
            raise ValueError(f"chain {chain_id!r} is declared more than once")
        if len(residue_ids) + length > _MAX_RESIDUES:
            raise ValueError("layout exceeds the supported residue bound")
        chain_ids.append(chain_id)
        residue_ids.extend(
            f"{chain_id}:{residue_number}"
            for residue_number in range(1, length + 1)
        )
    return ResidueLayout(
        chain_id=",".join(chain_ids),
        length=len(residue_ids),
        residue_ids=residue_ids,
    )


def build_residue_map(
    source_layout: ResidueLayout,
    target_layout: ResidueLayout,
    edits: Sequence[ResidueEditDeclaration],
) -> ResidueMap:
    """Reconcile explicit insert/delete declarations into one residue map."""
    source_ids = tuple(source_layout.residue_ids or ())
    target_ids = tuple(target_layout.residue_ids or ())
    source_set = set(source_ids)
    target_set = set(target_ids)
    common = source_set & target_set
    if [item for item in source_ids if item in common] != [
        item for item in target_ids if item in common
    ]:
        raise ValueError("residue edits cannot reorder preserved residues")

    declared_insertions: set[str] = set()
    declared_deletions: set[str] = set()
    touched: set[str] = set()
    for raw_edit in edits:
        operation = raw_edit["operation"]
        chain_id = raw_edit["chain_id"]
        residue_id = raw_edit["residue_id"]
        if residue_chain(residue_id) != chain_id:
            raise ValueError(
                "residue edit contradicts the residue's chain identity"
            )
        if residue_id in touched:
            raise ValueError(
                f"edits overlap at residue identity {residue_id!r}"
            )
        touched.add(residue_id)
        if operation == "insert":
            if residue_id not in target_set or residue_id in source_set:
                raise ValueError(
                    f"insert residue {residue_id!r} is outside the target delta"
                )
            declared_insertions.add(residue_id)
        else:
            if residue_id not in source_set or residue_id in target_set:
                raise ValueError(
                    f"delete residue {residue_id!r} is outside the source delta"
                )
            declared_deletions.add(residue_id)

    expected_insertions = target_set - source_set
    expected_deletions = source_set - target_set
    if declared_insertions != expected_insertions:
        raise ValueError("edits do not declare the complete target insertions")
    if declared_deletions != expected_deletions:
        raise ValueError("edits do not declare the complete source deletions")
    if (
        source_layout.length
        + len(declared_insertions)
        - len(declared_deletions)
        != target_layout.length
    ):
        raise ValueError("residue edits produce target length drift")

    source_index = {
        residue_id: index for index, residue_id in enumerate(source_ids)
    }
    target_index = {
        residue_id: index for index, residue_id in enumerate(target_ids)
    }
    mappings = [
        (
            source_index.get(residue_id, -1),
            target_position,
            "match" if residue_id in source_index else "insert",
        )
        for target_position, residue_id in enumerate(target_ids)
    ]
    mappings.extend(
        (source_position, -1, "delete")
        for source_position, residue_id in enumerate(source_ids)
        if residue_id not in target_index
    )
    return ResidueMap(
        source_layout=source_layout,
        target_layout=target_layout,
        mappings=mappings,
    )


def validate_residue_map(value: object) -> ResidueMap:
    """Require one complete, one-to-one, identity-preserving residue map."""
    admitted = validate_canonical_residue_map(value, subject="residue_map")
    for subject, layout in (
        ("source layout", admitted.source_layout),
        ("target layout", admitted.target_layout),
    ):
        if layout.length > _MAX_RESIDUES:
            raise ValueError(f"{subject} length is outside the supported range")
    return admitted


def validate_track(
    track: object,
    *,
    kind: TrackKind,
    subject: str,
    expected_layout: ResidueLayout | None = None,
) -> AlignedResidueTrack:
    """Validate one complete nullable track against one exact layout."""
    if not isinstance(kind, TrackKind):
        raise ValueError("track kind must be one closed scientific domain")
    if type(track) is not AlignedResidueTrack:
        raise ValueError(f"{subject} must be an AlignedResidueTrack")
    layout = validate_layout(track.layout, subject=f"{subject} layout")
    if expected_layout is not None:
        target = validate_layout(
            expected_layout,
            subject=f"{subject} expected layout",
        )
        if layout != target:
            raise ValueError(
                f"{subject} residue identities do not match the expected layout"
            )
    if len(track.values) != layout.length:
        raise ValueError(f"{subject} length does not match its residue layout")
    for index, item in enumerate(track.values):
        if item is None:
            continue
        if kind is TrackKind.SEQUENCE:
            if (
                type(item) is not str
                or len(item) != 1
                or item not in "ACDEFGHIKLMNPQRSTVWYBXZJUO"
            ):
                raise ValueError(
                    f"{subject}[{index}] is not one amino-acid code"
                )
        elif kind is TrackKind.STRUCTURE:
            _validate_structure_value(item, subject=f"{subject}[{index}]")
        elif kind is TrackKind.VISIBILITY:
            if type(item) is not bool:
                raise ValueError(
                    f"{subject}[{index}] is not nullable visibility"
                )
        elif kind is TrackKind.SECONDARY_STRUCTURE:
            if type(item) is not str or item not in _SECONDARY_STRUCTURE:
                raise ValueError(
                    f"{subject}[{index}] is not one canonical SS8 value"
                )
        elif kind is TrackKind.SASA:
            if (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(item)
                or item < 0
            ):
                raise ValueError(
                    f"{subject}[{index}] is not nullable absolute SASA in "
                    "square angstroms"
                )
    return track


def _validate_coordinate(value: object, *, subject: str) -> None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            for item in value
        )
    ):
        raise ValueError(f"{subject} must be one finite Cartesian 3-vector")


def _validate_structure_value(value: object, *, subject: str) -> None:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{subject} must be one named atom coordinate map")
    for atom_name, coordinate in value.items():
        if (
            not isinstance(atom_name, str)
            or re.fullmatch(r"^[A-Z0-9][A-Z0-9']{0,3}$", atom_name) is None
        ):
            raise ValueError(f"{subject} contains an invalid atom name")
        _validate_coordinate(
            coordinate,
            subject=f"{subject}.{atom_name}",
        )


def map_track(
    track: AlignedResidueTrack,
    residue_map: ResidueMap,
) -> AlignedResidueTrack:
    """Explicitly convert one track through one validated residue map."""
    if track.layout != residue_map.source_layout:
        raise ValueError(
            "source track residue identities do not match the residue map"
        )
    values: list[Any] = [None] * residue_map.target_layout.length
    for source_index, target_index, operation in residue_map.mappings:
        if operation == "match":
            values[target_index] = track.values[source_index]
    return AlignedResidueTrack(
        layout=residue_map.target_layout,
        values=tuple(values),
    )


def override_track(
    track: AlignedResidueTrack,
    layout: ResidueLayout,
    overrides: Sequence[TrackOverrideDeclaration],
    *,
    kind: TrackKind,
) -> AlignedResidueTrack:
    """Apply identity-addressed clear/preserve/replace operations."""
    if track.layout != layout:
        raise ValueError(
            "input track residue identities do not match target_layout"
        )
    residue_index = {
        residue_id: index
        for index, residue_id in enumerate(layout.residue_ids or ())
    }
    touched: set[str] = set()
    values = list(track.values)
    for raw_override in overrides:
        action = raw_override["action"]
        residue_id = raw_override["residue_id"]
        if residue_id not in residue_index:
            raise ValueError(
                f"override residue {residue_id!r} is outside target_layout"
            )
        if residue_id in touched:
            raise ValueError(f"overrides overlap at {residue_id!r}")
        touched.add(residue_id)
        position = residue_index[residue_id]
        if action == "clear":
            values[position] = None
        elif action == "replace":
            replacement = raw_override["value"]
            values[position] = normalize_replacement(
                replacement,
                kind=kind,
            )
    return AlignedResidueTrack(
        layout=layout,
        values=tuple(values),
    )


def normalize_replacement(value: object, *, kind: TrackKind) -> object:
    """Normalize public structure authoring values to the domain shape."""
    if kind is not TrackKind.STRUCTURE:
        return value
    if not isinstance(value, Mapping) or set(value) != {"atom_coordinates"}:
        return value
    raw_atoms = value["atom_coordinates"]
    if not isinstance(raw_atoms, Sequence) or isinstance(
        raw_atoms,
        (str, bytes, bytearray),
    ):
        raise ValueError("atom_coordinates must be an ordered array")
    normalized: dict[str, tuple[object, ...]] = {}
    for index, raw_atom in enumerate(raw_atoms):
        if not isinstance(raw_atom, Mapping) or set(raw_atom) != {
            "atom_name",
            "coordinates",
        }:
            raise ValueError(
                f"atom_coordinates[{index}] must contain atom_name and coordinates"
            )
        atom_name = raw_atom["atom_name"]
        coordinates = raw_atom["coordinates"]
        if not isinstance(atom_name, str) or atom_name in normalized:
            raise ValueError("atom_coordinates contains an invalid duplicate atom")
        if not isinstance(coordinates, Sequence) or isinstance(
            coordinates,
            (str, bytes, bytearray),
        ):
            raise ValueError("coordinates must be one three-item array")
        normalized[atom_name] = tuple(coordinates)
    return normalized
