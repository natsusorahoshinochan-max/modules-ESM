"""Shared residue-layout and track invariants for prompt authoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Any

from datatypes import ResidueLayout, ResidueMap


_CHAIN_ID = re.compile(r"^[A-Za-z0-9]$")
_RESIDUE_ID = re.compile(
    r"^(?P<chain>[A-Za-z0-9]):(?P<label>[A-Za-z0-9][A-Za-z0-9_.-]{0,63})$"
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


def residue_chain(residue_id: str) -> str:
    """Return the chain encoded by one canonical residue identity."""
    if not isinstance(residue_id, str):
        raise ValueError("residue identity must be text")
    match = _RESIDUE_ID.fullmatch(residue_id)
    if match is None:
        raise ValueError(
            f"residue identity {residue_id!r} must be '<chain>:<label>'"
        )
    return match.group("chain")


def validate_layout(layout: object, *, subject: str) -> ResidueLayout:
    """Validate one identity-complete layout and its contiguous chains."""
    if type(layout) is not ResidueLayout:
        raise ValueError(f"{subject} must be a ResidueLayout")
    if (
        type(layout.length) is not int
        or layout.length <= 0
        or layout.length > _MAX_RESIDUES
    ):
        raise ValueError(f"{subject} length is outside the supported range")
    residue_ids = layout.residue_ids
    if residue_ids is None or len(residue_ids) != layout.length:
        raise ValueError(f"{subject} requires one identity for every residue")
    if len(set(residue_ids)) != len(residue_ids):
        raise ValueError(f"{subject} contains duplicate residue identities")

    chain_order: list[str] = []
    closed_chains: set[str] = set()
    previous: str | None = None
    for residue_id in residue_ids:
        chain = residue_chain(residue_id)
        if chain != previous:
            if chain in closed_chains:
                raise ValueError(
                    f"{subject} chain {chain!r} is not one contiguous boundary"
                )
            if previous is not None:
                closed_chains.add(previous)
            chain_order.append(chain)
            previous = chain
    declared_chain_id = ",".join(chain_order)
    if layout.chain_id != declared_chain_id:
        raise ValueError(
            f"{subject} chain_id must equal contiguous chain order "
            f"{declared_chain_id!r}"
        )
    return layout


def build_layout(chains: object) -> ResidueLayout:
    """Construct a canonical layout from ordered chain lengths."""
    if not isinstance(chains, Sequence) or isinstance(
        chains, (str, bytes, bytearray)
    ):
        raise ValueError("chains must be an ordered array")
    if not chains:
        raise ValueError("chains must contain at least one chain")
    chain_ids: list[str] = []
    residue_ids: list[str] = []
    for index, raw_chain in enumerate(chains):
        if not isinstance(raw_chain, Mapping) or set(raw_chain) != {
            "chain_id",
            "length",
        }:
            raise ValueError(
                f"chains[{index}] must contain only chain_id and length"
            )
        chain_id = raw_chain["chain_id"]
        length = raw_chain["length"]
        if (
            not isinstance(chain_id, str)
            or _CHAIN_ID.fullmatch(chain_id) is None
        ):
            raise ValueError(f"chains[{index}].chain_id is invalid")
        if chain_id in chain_ids:
            raise ValueError(f"chain {chain_id!r} is declared more than once")
        if type(length) is not int or length <= 0 or length > _MAX_RESIDUES:
            raise ValueError(f"chains[{index}].length is invalid")
        if len(residue_ids) + length > _MAX_RESIDUES:
            raise ValueError("layout exceeds the supported residue bound")
        chain_ids.append(chain_id)
        residue_ids.extend(
            f"{chain_id}:{residue_number}"
            for residue_number in range(1, length + 1)
        )
    return validate_layout(
        ResidueLayout(
            chain_id=",".join(chain_ids),
            length=len(residue_ids),
            residue_ids=residue_ids,
        ),
        subject="constructed layout",
    )


def build_residue_map(
    source_layout: object,
    target_layout: object,
    edits: object,
) -> ResidueMap:
    """Reconcile explicit insert/delete declarations into one residue map."""
    source = validate_layout(source_layout, subject="source_layout")
    target = validate_layout(target_layout, subject="target_layout")
    if not isinstance(edits, Sequence) or isinstance(
        edits, (str, bytes, bytearray)
    ):
        raise ValueError("edits must be an ordered array")

    source_ids = tuple(source.residue_ids or ())
    target_ids = tuple(target.residue_ids or ())
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
    for index, raw_edit in enumerate(edits):
        if not isinstance(raw_edit, Mapping) or set(raw_edit) != {
            "operation",
            "chain_id",
            "residue_id",
        }:
            raise ValueError(
                f"edits[{index}] must contain operation, chain_id, and residue_id"
            )
        operation = raw_edit["operation"]
        chain_id = raw_edit["chain_id"]
        residue_id = raw_edit["residue_id"]
        if operation not in {"insert", "delete"}:
            raise ValueError(f"edits[{index}].operation is invalid")
        if not isinstance(chain_id, str) or residue_chain(residue_id) != chain_id:
            raise ValueError(
                f"edits[{index}] contradicts the residue's chain identity"
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
        source.length
        + len(declared_insertions)
        - len(declared_deletions)
        != target.length
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
    return validate_residue_map(
        ResidueMap(
            source_layout=source,
            target_layout=target,
            mappings=mappings,
        )
    )


def validate_residue_map(value: object) -> ResidueMap:
    """Require one complete, one-to-one, identity-preserving residue map."""
    if type(value) is not ResidueMap:
        raise ValueError("residue_map must be a ResidueMap")
    source = validate_layout(value.source_layout, subject="source layout")
    target = validate_layout(value.target_layout, subject="target layout")
    source_ids = tuple(source.residue_ids or ())
    target_ids = tuple(target.residue_ids or ())
    common_ids = set(source_ids) & set(target_ids)
    covered_sources: set[int] = set()
    covered_targets: set[int] = set()
    matched_ids: set[str] = set()
    for entry in value.mappings:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("residue_map entries must be three-item tuples")
        source_index, target_index, operation = entry
        if operation == "match":
            if (
                source_index in covered_sources
                or target_index in covered_targets
                or not 0 <= source_index < source.length
                or not 0 <= target_index < target.length
            ):
                raise ValueError("residue_map contains overlapping match entries")
            if source_ids[source_index] != target_ids[target_index]:
                raise ValueError(
                    "residue_map matches contradictory residue identities"
                )
            covered_sources.add(source_index)
            covered_targets.add(target_index)
            matched_ids.add(source_ids[source_index])
        elif operation == "insert":
            if (
                source_index != -1
                or target_index in covered_targets
                or not 0 <= target_index < target.length
                or target_ids[target_index] in common_ids
            ):
                raise ValueError("residue_map contains invalid insert entries")
            covered_targets.add(target_index)
        elif operation == "delete":
            if (
                target_index != -1
                or source_index in covered_sources
                or not 0 <= source_index < source.length
                or source_ids[source_index] in common_ids
            ):
                raise ValueError("residue_map contains invalid delete entries")
            covered_sources.add(source_index)
        else:
            raise ValueError("residue_map operation is invalid")
    if covered_sources != set(range(source.length)):
        raise ValueError("residue_map does not cover every source residue")
    if covered_targets != set(range(target.length)):
        raise ValueError("residue_map does not cover every target residue")
    if matched_ids != common_ids:
        raise ValueError(
            "residue_map must match every identity preserved by both layouts"
        )
    return value


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
                    f"{subject}[{index}] is not nullable non-negative SASA"
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
    track: object,
    residue_map: object,
    *,
    kind: TrackKind,
) -> AlignedResidueTrack:
    """Explicitly convert one track through one validated residue map."""
    mapping = validate_residue_map(residue_map)
    source = validate_track(
        track,
        kind=kind,
        subject="source track",
        expected_layout=mapping.source_layout,
    )
    values: list[Any] = [None] * mapping.target_layout.length
    for source_index, target_index, operation in mapping.mappings:
        if operation == "match":
            values[target_index] = source.values[source_index]
    result = AlignedResidueTrack(
        layout=mapping.target_layout,
        values=tuple(values),
    )
    return validate_track(
        result,
        kind=kind,
        subject="mapped track",
        expected_layout=mapping.target_layout,
    )


def override_track(
    track: object,
    layout: object,
    overrides: object,
    *,
    kind: TrackKind,
) -> AlignedResidueTrack:
    """Apply identity-addressed clear/preserve/replace operations."""
    target_layout = validate_layout(layout, subject="target_layout")
    source = validate_track(
        track,
        kind=kind,
        subject="input track",
        expected_layout=target_layout,
    )
    if not isinstance(overrides, Sequence) or isinstance(
        overrides, (str, bytes, bytearray)
    ):
        raise ValueError("overrides must be an ordered array")
    residue_index = {
        residue_id: index
        for index, residue_id in enumerate(target_layout.residue_ids or ())
    }
    touched: set[str] = set()
    values = list(source.values)
    for index, raw_override in enumerate(overrides):
        if not isinstance(raw_override, Mapping):
            raise ValueError(f"overrides[{index}] must be an object")
        action = raw_override.get("action")
        residue_id = raw_override.get("residue_id")
        expected_fields = (
            {"action", "residue_id", "value"}
            if action == "replace"
            else {"action", "residue_id"}
        )
        if set(raw_override) != expected_fields:
            raise ValueError(
                f"overrides[{index}] fields do not match {action!r}"
            )
        if action not in {"clear", "preserve", "replace"}:
            raise ValueError(f"overrides[{index}].action is invalid")
        if not isinstance(residue_id, str) or residue_id not in residue_index:
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
            if replacement is None:
                raise ValueError(
                    "replace requires a concrete value; use clear for null"
                )
            values[position] = normalize_replacement(
                replacement,
                kind=kind,
            )
    result = AlignedResidueTrack(
        layout=target_layout,
        values=tuple(values),
    )
    return validate_track(
        result,
        kind=kind,
        subject="overridden track",
        expected_layout=target_layout,
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
