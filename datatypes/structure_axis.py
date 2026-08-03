"""Provider-independent resolved residue-axis scientific values."""

from __future__ import annotations

from dataclasses import dataclass

from datatypes.protein import (
    ModifiedResidueNormalizationCollection,
    ProteinStructure,
    ResidueLayout,
)


Coordinate3D = tuple[float, float, float]


def _tuple(value: object, *, name: str) -> tuple:
    if type(value) not in (list, tuple):
        raise TypeError(f"{name} must be an ordered list or tuple")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class StructureAtomCoordinate:
    """One selected canonical atom coordinate on a resolved residue axis."""

    atom_name: str
    coordinate: Coordinate3D

    def __post_init__(self) -> None:
        coordinate = _tuple(self.coordinate, name="coordinate")
        if len(coordinate) != 3:
            raise ValueError("coordinate must contain exactly three values")
        object.__setattr__(self, "coordinate", coordinate)


@dataclass(frozen=True, slots=True)
class StructureResidueCoordinates:
    """Selected coordinates for one identity-complete axis residue."""

    residue_id: str
    atom_coordinates: tuple[StructureAtomCoordinate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "atom_coordinates",
            _tuple(self.atom_coordinates, name="atom_coordinates"),
        )


@dataclass(frozen=True, slots=True)
class StructureAxisSegment:
    """One ordered covalent segment of a resolved protein residue axis."""

    segment_index: int
    chain_id: str
    residue_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "residue_ids",
            _tuple(self.residue_ids, name="residue_ids"),
        )


@dataclass(frozen=True, slots=True)
class StructureComponentDisposition:
    """Exact scientific disposition of one structure component."""

    component_id: str
    observed_residue_id: str
    record_type: str
    component_role: str
    disposition: str
    parent_residue_ids: tuple[str, ...]
    parent_sequence: str
    normalization_source: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parent_residue_ids",
            _tuple(self.parent_residue_ids, name="parent_residue_ids"),
        )


@dataclass(frozen=True, slots=True)
class ResolvedStructureResidueAxis:
    """One admitted structure, protein axis, topology, and component inventory."""

    structure: ProteinStructure
    layout: ResidueLayout
    sequence: str
    residue_names: tuple[str, ...]
    segments: tuple[StructureAxisSegment, ...]
    component_dispositions: tuple[StructureComponentDisposition, ...]
    modified_residue_normalizations: ModifiedResidueNormalizationCollection
    residue_coordinates: tuple[StructureResidueCoordinates, ...]
    ca_coordinate_mask: tuple[bool, ...]
    complete_backbone_mask: tuple[bool, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "residue_names",
            "segments",
            "component_dispositions",
            "residue_coordinates",
            "ca_coordinate_mask",
            "complete_backbone_mask",
        ):
            object.__setattr__(
                self,
                field_name,
                _tuple(getattr(self, field_name), name=field_name),
            )

    def coordinates_for(
        self,
        residue_id: str,
    ) -> tuple[StructureAtomCoordinate, ...]:
        """Return admitted coordinates for one exact residue identity."""
        for item in self.residue_coordinates:
            if item.residue_id == residue_id:
                return item.atom_coordinates
        raise KeyError(f"resolved residue axis has no residue {residue_id}")

    def coordinate_for(self, residue_id: str, atom_name: str) -> Coordinate3D:
        """Return one admitted named-atom coordinate without reparsing PDB."""
        for item in self.coordinates_for(residue_id):
            if item.atom_name == atom_name:
                return item.coordinate
        raise KeyError(
            f"resolved residue axis residue {residue_id} has no atom {atom_name}"
        )

    def backbone_coordinates_for(
        self,
        residue_id: str,
    ) -> dict[str, Coordinate3D]:
        """Return the admitted subset of canonical N/CA/C/O coordinates."""
        return {
            item.atom_name: item.coordinate
            for item in self.coordinates_for(residue_id)
            if item.atom_name in {"N", "CA", "C", "O"}
        }
