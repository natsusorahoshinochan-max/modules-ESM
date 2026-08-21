"""Provider-independent protein structure and resolved-axis values."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re

from datatypes.residue import ModifiedResidueNormalizationCollection, ResidueLayout


_PDB_RECORD_NAMES = frozenset({
    "ANISOU", "ATOM", "AUTHOR", "CAVEAT", "CISPEP", "COMPND", "CONECT",
    "CRYST1", "DBREF", "DBREF1", "DBREF2", "END", "ENDMDL", "EXPDTA",
    "FORMUL", "HEADER", "HELIX", "HET", "HETATM", "HETNAM", "HETSYN",
    "JRNL", "KEYWDS",
    "LINK", "MASTER", "MDLTYP", "MODEL", "MODRES", "MTRIX1", "MTRIX2",
    "MTRIX3", "NUMMDL", "OBSLTE", "ORIGX1", "ORIGX2", "ORIGX3", "REMARK",
    "REVDAT", "SCALE1", "SCALE2", "SCALE3", "SEQADV", "SEQRES", "SHEET",
    "SIGATM", "SIGUIJ", "SITE", "SOURCE", "SPLIT", "SPRSDE", "SSBOND",
    "TER", "TITLE", "TVECT",
})

@dataclass(frozen=True, slots=True)
class ProteinStructure:
    """Canonical PDB string representation of a protein structure.

    pdb_string: full PDB-format text.
    """

    pdb_string: str


def validate_protein_structure(
    value: object,
    *,
    subject: str = "protein structure",
) -> ProteinStructure:
    """Admit canonical PDB text without imposing operation-specific biology."""
    if type(value) is not ProteinStructure:
        raise ValueError(f"{subject} must be a ProteinStructure")
    pdb_string = value.pdb_string
    if (
        type(pdb_string) is not str
        or not pdb_string
        or not pdb_string.isascii()
        or "\r" in pdb_string
        or "\t" in pdb_string
        or not pdb_string.endswith("\n")
        or pdb_string.endswith("\n\n")
    ):
        raise ValueError(f"{subject} must contain canonical PDB text")

    lines = pdb_string.splitlines()
    record_names = tuple(line[:6].strip() for line in lines)
    if (
        not lines
        or record_names[-1] != "END"
        or lines[-1][6:].strip()
        or "END" in record_names[:-1]
    ):
        raise ValueError(
            f"{subject} canonical PDB text must end with exactly one END record"
        )

    has_model_records = "MODEL" in record_names
    model_is_open = False
    model_coordinate_count = 0
    coordinate_count = 0
    for line_number, (line, record_name) in enumerate(
        zip(lines[:-1], record_names[:-1], strict=True),
        start=1,
    ):
        if record_name not in _PDB_RECORD_NAMES:
            raise ValueError(
                f"{subject} line {line_number} has a non-canonical PDB record"
            )
        if record_name == "MODEL":
            if (
                model_is_open
                or len(line) < 14
                or line[:6] != "MODEL "
                or line[6:10] != "    "
                or not line[10:14].strip().isdigit()
                or int(line[10:14]) <= 0
                or line[14:].strip()
            ):
                raise ValueError(
                    f"{subject} contains non-canonical PDB model boundaries"
                )
            model_is_open = True
            model_coordinate_count = 0
            continue
        if record_name == "ENDMDL":
            if not model_is_open or model_coordinate_count == 0 or line[6:].strip():
                raise ValueError(
                    f"{subject} contains non-canonical PDB model boundaries"
                )
            model_is_open = False
            continue
        if not line.startswith(("ATOM  ", "HETATM")):
            if line.startswith(("ATOM", "HETATM")):
                raise ValueError(
                    f"{subject} line {line_number} is not a canonical PDB "
                    "coordinate record"
                )
            continue
        if has_model_records and not model_is_open:
            raise ValueError(
                f"{subject} contains coordinates outside canonical PDB model "
                "boundaries"
            )
        if len(line) != 80:
            raise ValueError(
                f"{subject} line {line_number} is not a canonical PDB "
                "coordinate record"
            )
        try:
            serial = int(line[6:11])
            int(line[22:26])
            coordinates = tuple(
                float(line[start : start + 8])
                for start in (30, 38, 46)
            )
            occupancy = float(line[54:60])
            temperature_factor = float(line[60:66])
        except ValueError as error:
            raise ValueError(
                f"{subject} line {line_number} is not a canonical PDB "
                "coordinate record"
            ) from error
        element_field = line[76:78]
        element = element_field.strip()
        charge = line[78:80]
        chain_id = line[21]
        insertion_code = line[26]
        if (
            serial <= 0
            or line[11] != " "
            or not line[12:16].strip()
            or not line[17:20].strip()
            or line[20] != " "
            or not chain_id.isascii()
            or not chain_id.isalnum()
            or (
                insertion_code != " "
                and (
                    not insertion_code.isascii()
                    or not insertion_code.isalpha()
                )
            )
            or line[27:30] != "   "
            or line[66:76] != " " * 10
            or not all(
                isfinite(value)
                for value in (
                    *coordinates,
                    occupancy,
                    temperature_factor,
                )
            )
            or not element
            or not element.isalpha()
            or not element.isascii()
            or element_field != element.rjust(2)
            or (
                charge != " " * 2
                and re.fullmatch(r"[0-9][+-]", charge) is None
            )
        ):
            raise ValueError(
                f"{subject} line {line_number} is not a canonical PDB "
                "coordinate record"
            )
        coordinate_count += 1
        model_coordinate_count += 1

    if model_is_open:
        raise ValueError(
            f"{subject} contains non-canonical PDB model boundaries"
        )
    if coordinate_count == 0:
        raise ValueError(
            f"{subject} canonical PDB text must contain a coordinate record"
        )
    return value

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
