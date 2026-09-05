"""Shared residue-layout and track invariants for prompt authoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any, Literal, NotRequired, TypedDict

from datatypes.residue import (
    ResidueLayout,
    residue_identity_chain,
    validate_residue_layout,
)
from datatypes.structure import NamedAtomCoordinates
from modules.residue_data.port_types import AMINO_ACIDS, CANONICAL_SS8


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
    return validate_residue_layout(layout, subject=subject)


def build_layout(chains: Sequence[ChainDeclaration]) -> ResidueLayout:
    """Construct a canonical layout from ordered chain declarations."""
    chain_ids: list[str] = []
    residue_ids: list[str] = []
    for raw_chain in chains:
        chain_id = raw_chain["chain_id"]
        length = raw_chain["length"]
        if chain_id in chain_ids:
            raise ValueError(f"chain {chain_id!r} is declared more than once")
        chain_ids.append(chain_id)
        residue_ids.extend(
            f"{chain_id}:{residue_number}"
            for residue_number in range(1, length + 1)
        )
    return ResidueLayout(residue_ids=residue_ids)


def validate_track_values(
    values: Sequence[object],
    *,
    kind: str,
    subject: str,
    length: int,
) -> None:
    """Validate one complete nullable track against its element contract.

    ``kind`` is one of ``sequence``, ``coordinates``,
    ``secondary_structure``, or ``sasa``. The nominal Port Types own the
    same contracts; this helper exists so Prompt assembly and overrides
    validate values before constructing the closed aggregate.
    """
    if len(values) != length:
        raise ValueError(f"{subject} length does not match its residue layout")
    for index, item in enumerate(values):
        if item is None:
            continue
        if kind == "sequence":
            if (
                type(item) is not str
                or len(item) != 1
                or item not in AMINO_ACIDS
            ):
                raise ValueError(
                    f"{subject}[{index}] is not one amino-acid code"
                )
        elif kind == "coordinates":
            if type(item) is not NamedAtomCoordinates:
                raise ValueError(
                    f"{subject}[{index}] is not one NamedAtomCoordinates"
                )
        elif kind == "secondary_structure":
            if type(item) is not str or item not in CANONICAL_SS8:
                raise ValueError(
                    f"{subject}[{index}] is not one canonical SS8 value"
                )
        elif kind == "sasa":
            if (
                isinstance(item, bool)
                or type(item) is not float
                or not math.isfinite(item)
                or item < 0
            ):
                raise ValueError(
                    f"{subject}[{index}] is not nullable absolute SASA in "
                    "square angstroms"
                )
        else:
            raise ValueError(f"unknown prompt track kind {kind!r}")


def validate_track(
    track: object,
    *,
    kind: str,
    subject: str,
) -> ResidueTrack[Any]:
    """Validate one complete layout-bound track of one declared kind."""
    if type(track) is not ResidueTrack:
        raise ValueError(f"{subject} must be a ResidueTrack")
    layout = validate_layout(track.layout, subject=f"{subject} layout")
    validate_track_values(
        track.values,
        kind=kind,
        subject=subject,
        length=layout.length,
    )
    return track


def normalize_replacement(value: object) -> NamedAtomCoordinates:
    """Normalize public structure authoring values to the domain shape."""
    if isinstance(value, NamedAtomCoordinates):
        return value
    if not isinstance(value, Mapping) or "atom_coordinates" not in value:
        raise ValueError(
            "structure override value must carry atom_coordinates"
        )
    raw_atoms = value["atom_coordinates"]
    atoms: dict[str, tuple[float, float, float]] = {}
    for raw_atom in raw_atoms:
        atom_name = raw_atom["atom_name"]
        if atom_name in atoms:
            raise ValueError("atom_coordinates contains a duplicate atom")
        coordinate = tuple(raw_atom["coordinates"])
        if len(coordinate) != 3:
            raise ValueError(
                f"atom {atom_name!r} coordinate must be one Cartesian "
                "3-vector"
            )
        atoms[atom_name] = coordinate  # type: ignore[assignment]
    return NamedAtomCoordinates.from_mapping(atoms)


def override_values(
    values: Sequence[object],
    layout: ResidueLayout,
    overrides: Sequence[TrackOverrideDeclaration],
    *,
    kind: str,
) -> tuple[Any | None, ...]:
    """Apply identity-addressed clear/preserve/replace operations."""
    residue_index = {
        residue_id: index
        for index, residue_id in enumerate(layout.residue_ids)
    }
    touched: set[str] = set()
    updated = list(values)
    for raw_override in overrides:
        action = raw_override["action"]
        residue_id = raw_override["residue_id"]
        if residue_id not in residue_index:
            raise ValueError(
                f"override residue {residue_id!r} is outside the prompt layout"
            )
        if residue_id in touched:
            raise ValueError(f"overrides overlap at {residue_id!r}")
        touched.add(residue_id)
        position = residue_index[residue_id]
        if action == "clear":
            updated[position] = None
        elif action == "replace":
            replacement = raw_override["value"]
            if kind == "coordinates":
                replacement = normalize_replacement(replacement)
            updated[position] = replacement
    return tuple(updated)
