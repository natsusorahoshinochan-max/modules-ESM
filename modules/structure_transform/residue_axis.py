"""Resolved structure residue-axis parsing and coordinate semantics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Mapping, cast

from core.operation import (
    OperationResources,
    OperationCall,
)
from datatypes.residue import (
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    ResidueLayout,
)
from datatypes.structure import (
    ProteinStructure,
    ResolvedStructureResidueAxis,
    StructureAtomCoordinate,
    StructureAxisSegment,
    StructureComponentDisposition,
    StructureResidueCoordinates,
)


_BACKBONE_ATOMS = ("N", "CA", "C", "O")
_AMINO_ACIDS = {
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
_WATER_COMPONENTS = {"DOD", "HOH", "WAT"}


@dataclass(frozen=True, slots=True)
class _AtomRecord:
    line: str
    record: str
    atom_name: str
    altloc: str
    residue_name: str
    chain_id: str
    residue_number: str
    insertion_code: str

    @property
    def residue_identity(self) -> tuple[str, str, str]:
        return (self.chain_id, self.residue_number, self.insertion_code)

    @property
    def public_residue_id(self) -> str:
        label = self.residue_number + self.insertion_code
        return f"{self.chain_id}:{label}"


def _atom_record(line: str) -> _AtomRecord:
    record = line[:6]
    chain_id = line[21]
    residue_number = line[22:26].strip()
    insertion_code = line[26].strip()
    return _AtomRecord(
        line=line,
        record=record,
        atom_name=line[12:16].strip(),
        altloc=line[16],
        residue_name=line[17:20].strip(),
        chain_id=chain_id,
        residue_number=residue_number,
        insertion_code=insertion_code,
    )


def _single_model_records(
    structure: ProteinStructure,
) -> list[_AtomRecord | None]:
    lines = structure.pdb_string.splitlines()
    model_count = sum(line.startswith("MODEL ") for line in lines)
    end_model_count = sum(line.startswith("ENDMDL") for line in lines)
    if model_count > 1 or end_model_count > 1:
        raise ValueError("structure transforms require exactly one PDB model")
    if model_count != end_model_count:
        raise ValueError("PDB MODEL and ENDMDL records are unbalanced")

    records: list[_AtomRecord | None] = []
    last_was_break = True
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            records.append(_atom_record(line))
            last_was_break = False
        elif line.startswith("TER"):
            if not last_was_break:
                records.append(None)
                last_was_break = True
    while records and records[-1] is None:
        records.pop()
    if not records or not any(record is not None for record in records):
        raise ValueError("structure contains no PDB coordinate records")
    return records


def _coordinate_segments(
    records: list[_AtomRecord | None],
) -> list[list[_AtomRecord]]:
    result: list[list[_AtomRecord]] = []
    current: list[_AtomRecord] = []
    current_chain: str | None = None
    for record in records:
        if record is None:
            if current:
                result.append(current)
                current = []
                current_chain = None
            continue
        if current and record.chain_id != current_chain:
            result.append(current)
            current = []
        current_chain = record.chain_id
        current.append(record)
    if current:
        result.append(current)
    return result


def _choose_alternate(
    records: list[_AtomRecord],
    *,
    residue_id: str,
    atom_name: str,
) -> _AtomRecord:
    by_altloc: dict[str, _AtomRecord] = {}
    for record in records:
        if record.altloc in by_altloc:
            raise ValueError(
                f"residue {residue_id} has duplicate {atom_name} "
                f"alternate location {record.altloc!r}"
            )
        by_altloc[record.altloc] = record
    if " " in by_altloc:
        return by_altloc[" "]
    if "A" in by_altloc:
        return by_altloc["A"]
    raise ValueError(
        f"residue {residue_id} {atom_name} has no blank or A "
        "alternate location"
    )


@dataclass(frozen=True, slots=True)
class _CoordinateComponent:
    segment_index: int
    records: tuple[_AtomRecord, ...]

    @property
    def representative(self) -> _AtomRecord:
        return self.records[0]


def _coordinate_components(
    structure: ProteinStructure,
) -> tuple[_CoordinateComponent, ...]:
    records = _single_model_records(structure)
    component_segment_indices: list[int] = []
    component_records: list[list[_AtomRecord]] = []
    seen: set[tuple[str, str, str]] = set()
    segment_index = -1
    current_chain: str | None = None
    segment_boundary = True
    for record in records:
        if record is None:
            segment_boundary = True
            current_chain = None
            continue
        if segment_boundary or record.chain_id != current_chain:
            segment_index += 1
            current_chain = record.chain_id
            segment_boundary = False
        if (
            not component_records
            or component_segment_indices[-1] != segment_index
            or component_records[-1][0].residue_identity
            != record.residue_identity
        ):
            if record.residue_identity in seen:
                raise ValueError(
                    f"residue {record.public_residue_id} is noncontiguous"
                )
            seen.add(record.residue_identity)
            component_segment_indices.append(segment_index)
            component_records.append([record])
            continue
        component_records[-1].append(record)
    return tuple(
        _CoordinateComponent(segment_index, tuple(records))
        for segment_index, records in zip(
            component_segment_indices,
            component_records,
            strict=True,
        )
    )


def _pdb_polymer_declarations(
    structure: ProteinStructure,
) -> tuple[
    dict[tuple[str, str, str], tuple[str, str]],
    dict[str, tuple[str, ...]],
]:
    modres: dict[tuple[str, str, str], tuple[str, str]] = {}
    seqres_records: dict[str, dict[int, tuple[str, ...]]] = defaultdict(dict)
    seqres_counts: dict[str, int] = {}
    for line in structure.pdb_string.splitlines():
        if line.startswith("MODRES"):
            if len(line) < 27:
                raise ValueError("PDB MODRES record is truncated")
            component_id = line[12:15].strip().upper()
            chain_id = line[16]
            residue_number = line[18:22].strip()
            insertion_code = line[22].strip()
            parent_name = line[24:27].strip().upper()
            identity = (chain_id, residue_number, insertion_code)
            if (
                not component_id
                or not chain_id.isalnum()
                or not residue_number
                or parent_name not in _AMINO_ACIDS
                or identity in modres
            ):
                raise ValueError("PDB MODRES residue declaration is invalid")
            modres[identity] = (component_id, parent_name)
        elif line.startswith("SEQRES"):
            if len(line) < 19:
                raise ValueError("PDB SEQRES record is invalid")
            chain_id = line[11]
            try:
                serial = int(line[7:10])
                declared_count = int(line[13:17])
            except ValueError as error:
                raise ValueError("PDB SEQRES record is invalid") from error
            components = tuple(line[19:].split())
            if (
                not chain_id.isascii()
                or not chain_id.isalnum()
                or serial <= 0
                or declared_count <= 0
                or not components
                or len(components) > 13
                or any(
                    not component.isascii()
                    or not component.isalnum()
                    or component != component.upper()
                    or len(component) > 3
                    for component in components
                )
                or serial in seqres_records[chain_id]
                or (
                    chain_id in seqres_counts
                    and seqres_counts[chain_id] != declared_count
                )
            ):
                raise ValueError("PDB SEQRES record is invalid")
            seqres_records[chain_id][serial] = components
            seqres_counts[chain_id] = declared_count
    seqres: dict[str, tuple[str, ...]] = {}
    for chain_id, records in seqres_records.items():
        serials = sorted(records)
        if serials != list(range(1, len(serials) + 1)):
            raise ValueError("PDB SEQRES serials are not contiguous")
        components = tuple(
            component
            for serial in serials
            for component in records[serial]
        )
        if len(components) != seqres_counts[chain_id]:
            raise ValueError("PDB SEQRES declared residue count is inconsistent")
        seqres[chain_id] = components
    return modres, seqres


def _subsequence_position_bounds(
    observed: tuple[str, ...],
    deposited: tuple[str, ...],
) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    earliest: list[int] = []
    cursor = 0
    for component_id in observed:
        while cursor < len(deposited) and deposited[cursor] != component_id:
            cursor += 1
        if cursor == len(deposited):
            return None
        earliest.append(cursor)
        cursor += 1

    latest = [0] * len(observed)
    cursor = len(deposited) - 1
    for index in range(len(observed) - 1, -1, -1):
        component_id = observed[index]
        while cursor >= 0 and deposited[cursor] != component_id:
            cursor -= 1
        if cursor < 0:
            return None
        latest[index] = cursor
        cursor -= 1
    return tuple(earliest), tuple(latest)


def _seqres_consistent_mse_identities(
    components: tuple[_CoordinateComponent, ...],
    modres: Mapping[tuple[str, str, str], tuple[str, str]],
    seqres: Mapping[str, tuple[str, ...]],
) -> set[tuple[str, str, str]]:
    exact_mse_components = tuple(
        component
        for component in components
        if component.representative.residue_name == "MSE"
        and modres.get(component.representative.residue_identity)
        == ("MSE", "MET")
    )
    consistent: set[tuple[str, str, str]] = set()
    for chain_id in dict.fromkeys(
        component.representative.chain_id
        for component in exact_mse_components
    ):
        deposited = seqres.get(chain_id)
        if deposited is None:
            continue
        deposited_components = set(deposited)
        observed_components = tuple(
            component
            for component in components
            if component.representative.chain_id == chain_id
            and (
                component.representative.residue_name in _AMINO_ACIDS
                or component.representative.residue_identity in modres
                or component.representative.residue_name
                in deposited_components
                and {"N", "CA", "C"}.issubset(
                    record.atom_name for record in component.records
                )
            )
        )
        observed_names = tuple(
            component.representative.residue_name
            for component in observed_components
        )
        position_bounds = _subsequence_position_bounds(
            observed_names,
            deposited,
        )
        if position_bounds is None:
            observed_mse = next(
                component
                for component in exact_mse_components
                if component.representative.chain_id == chain_id
            )
            raise ValueError(
                "unsupported_modified_polymer: MSE at "
                f"{observed_mse.representative.public_residue_id} lacks "
                "unique SEQRES correspondence"
            )
        earliest, latest = position_bounds
        for index, component in enumerate(observed_components):
            representative = component.representative
            if (
                representative.residue_name != "MSE"
                or modres.get(representative.residue_identity)
                != ("MSE", "MET")
            ):
                continue
            if earliest[index] != latest[index]:
                raise ValueError(
                    "unsupported_modified_polymer: MSE at "
                    f"{representative.public_residue_id} lacks unique "
                    "SEQRES correspondence"
                )
            consistent.add(representative.residue_identity)
    return consistent


def _selected_coordinates(
    component: _CoordinateComponent,
    *,
    atom_renames: Mapping[str, str] | None = None,
) -> tuple[StructureAtomCoordinate, ...]:
    representative = component.representative
    residue_names = {record.residue_name for record in component.records}
    record_types = {record.record for record in component.records}
    if len(residue_names) != 1 or len(record_types) != 1:
        raise ValueError(
            f"component {representative.public_residue_id} is ambiguous"
        )
    by_atom: dict[str, list[_AtomRecord]] = defaultdict(list)
    atom_order: list[str] = []
    for record in component.records:
        if record.atom_name not in by_atom:
            atom_order.append(record.atom_name)
        by_atom[record.atom_name].append(record)
    selected: list[StructureAtomCoordinate] = []
    emitted_names: set[str] = set()
    for source_atom_name in atom_order:
        record = _choose_alternate(
            by_atom[source_atom_name],
            residue_id=representative.public_residue_id,
            atom_name=source_atom_name,
        )
        atom_name = (
            atom_renames.get(source_atom_name, source_atom_name)
            if atom_renames is not None
            else source_atom_name
        )
        if atom_name in emitted_names:
            raise ValueError(
                f"component {representative.public_residue_id} normalizes "
                f"duplicate atom {atom_name}"
            )
        coordinate = tuple(
            0.0 if value == 0.0 else value
            for value in (
                float(record.line[30:38]),
                float(record.line[38:46]),
                float(record.line[46:54]),
            )
        )
        if not all(math.isfinite(value) for value in coordinate):
            raise ValueError("resolved residue coordinate is non-finite")
        emitted_names.add(atom_name)
        selected.append(StructureAtomCoordinate(atom_name, coordinate))
    return tuple(selected)


def resolve_residue_axis(
    structure: object,
    normalizations: object | None = None,
) -> ResolvedStructureResidueAxis:
    """Resolve one structure into the sole admitted protein residue axis."""
    admitted_structure = cast(ProteinStructure, structure)
    supplied_normalizations = (
        ModifiedResidueNormalizationCollection()
        if normalizations is None
        else cast(ModifiedResidueNormalizationCollection, normalizations)
    )

    modres, seqres = _pdb_polymer_declarations(admitted_structure)
    components = _coordinate_components(admitted_structure)
    seqres_consistent_mse = _seqres_consistent_mse_identities(
        components,
        modres,
        seqres,
    )
    layout_ids: list[str] = []
    layout_id_set: set[str] = set()
    layout_index_by_id: dict[str, int] = {}
    sequence: list[str] = []
    residue_names: list[str] = []
    coordinates: list[StructureResidueCoordinates] = []
    ca_mask: list[bool] = []
    backbone_mask: list[bool] = []
    dispositions: list[StructureComponentDisposition] = []
    generated_normalizations: list[ModifiedResidueNormalization] = []
    segment_residue_ids: dict[int, list[str]] = {}
    segment_chain_ids: dict[int, str] = {}
    segment_order: list[int] = []

    for component in components:
        representative = component.representative
        if (
            len({record.residue_name for record in component.records}) != 1
            or len({record.record for record in component.records}) != 1
        ):
            raise ValueError(
                f"component {representative.public_residue_id} is ambiguous"
            )
        component_id = representative.residue_name.upper()
        residue_id = representative.public_residue_id
        record_type = representative.record.strip()
        source_atom_names = {record.atom_name for record in component.records}
        declaration = modres.get(representative.residue_identity)

        if component_id in _WATER_COMPONENTS:
            dispositions.append(
                StructureComponentDisposition(
                    component_id,
                    residue_id,
                    record_type,
                    "water",
                    "excluded",
                    (),
                    "",
                    None,
                )
            )
            continue
        if (
            component_id == "MSE"
            and declaration is not None
            and declaration == ("MSE", "MET")
            and representative.residue_identity in seqres_consistent_mse
        ):
            atom_renames = {"SE": "SD"}
            atom_coordinates = _selected_coordinates(
                component,
                atom_renames=atom_renames,
            )
            letter = "M"
            parent_name = "MET"
            role = "modified_polymer"
            disposition = "normalized"
            normalization_source = "pdb_modres"
            generated_normalizations.append(
                ModifiedResidueNormalization(
                    component_id="MSE",
                    observed_residue_id=residue_id,
                    parent_residue_ids=(residue_id,),
                    parent_sequence="M",
                    atom_mappings=tuple(
                        ModifiedResidueAtomMapping(
                            source_atom_name=source_atom_name,
                            parent_residue_id=residue_id,
                            parent_atom_name=atom_renames.get(
                                source_atom_name,
                                source_atom_name,
                            ),
                        )
                        for source_atom_name in dict.fromkeys(
                            record.atom_name for record in component.records
                        )
                    ),
                )
            )
        elif component_id in _AMINO_ACIDS:
            letter = _AMINO_ACIDS[component_id]
            parent_name = component_id
            atom_coordinates = _selected_coordinates(component)
            role = "polymer"
            disposition = "included"
            normalization_source = None
        elif declaration is not None or (
            record_type == "HETATM"
            and (
                component_id == "CSH"
                or component_id
                in seqres.get(representative.chain_id, ())
                or {"N", "CA", "C"}.issubset(source_atom_names)
            )
        ):
            raise ValueError(
                "unsupported_modified_polymer: "
                f"{component_id} at {residue_id} requires an exact "
                "normalization contract"
            )
        elif record_type == "ATOM":
            raise ValueError(
                "unsupported_polymer_component: "
                f"{component_id} at {residue_id} requires an exact "
                "parent contract"
            )
        else:
            dispositions.append(
                StructureComponentDisposition(
                    component_id,
                    residue_id,
                    record_type,
                    "ligand",
                    "excluded",
                    (),
                    "",
                    None,
                )
            )
            continue

        if residue_id in layout_id_set:
            raise ValueError(f"resolved residue identity {residue_id} is duplicated")
        atom_names = {item.atom_name for item in atom_coordinates}
        layout_ids.append(residue_id)
        layout_id_set.add(residue_id)
        layout_index_by_id[residue_id] = len(layout_ids) - 1
        sequence.append(letter)
        residue_names.append(parent_name)
        coordinates.append(
            StructureResidueCoordinates(residue_id, atom_coordinates)
        )
        ca_mask.append("CA" in atom_names)
        backbone_mask.append(
            all(atom_name in atom_names for atom_name in _BACKBONE_ATOMS)
        )
        if component.segment_index not in segment_residue_ids:
            segment_order.append(component.segment_index)
            segment_residue_ids[component.segment_index] = []
            segment_chain_ids[component.segment_index] = representative.chain_id
        segment_residue_ids[component.segment_index].append(residue_id)
        dispositions.append(
            StructureComponentDisposition(
                component_id,
                residue_id,
                record_type,
                role,
                disposition,
                (residue_id,),
                letter,
                normalization_source,
            )
        )

    if not layout_ids:
        raise ValueError("resolved residue axis contains no polymer residues")

    for entry in supplied_normalizations.entries:
        if any(
            parent_id not in layout_id_set
            for parent_id in entry.parent_residue_ids
        ):
            raise ValueError(
                "modified-residue normalization parents are absent from axis"
            )
        for parent_id, letter in zip(
            entry.parent_residue_ids,
            entry.parent_sequence,
            strict=True,
        ):
            index = layout_index_by_id[parent_id]
            if sequence[index] != letter:
                raise ValueError(
                    "modified-residue normalization contradicts axis sequence"
                )
        dispositions.append(
            StructureComponentDisposition(
                entry.component_id,
                entry.observed_residue_id,
                "HETATM",
                "modified_polymer",
                "normalized",
                entry.parent_residue_ids,
                entry.parent_sequence,
                "explicit_mapping",
            )
        )

    segments = tuple(
        StructureAxisSegment(
            segment_index=index,
            chain_id=segment_chain_ids[source_index],
            residue_ids=tuple(segment_residue_ids[source_index]),
        )
        for index, source_index in enumerate(segment_order)
    )
    chain_order = tuple(dict.fromkeys(segment.chain_id for segment in segments))
    return ResolvedStructureResidueAxis(
        structure=structure,
        layout=ResidueLayout(
            chain_id=",".join(chain_order),
            length=len(layout_ids),
            residue_ids=tuple(layout_ids),
        ),
        sequence="".join(sequence),
        residue_names=tuple(residue_names),
        segments=segments,
        component_dispositions=tuple(dispositions),
        modified_residue_normalizations=ModifiedResidueNormalizationCollection(
            entries=(
                *supplied_normalizations.entries,
                *generated_normalizations,
            )
        ),
        residue_coordinates=tuple(coordinates),
        ca_coordinate_mask=tuple(ca_mask),
        complete_backbone_mask=tuple(backbone_mask),
    )


def _renumbered_atom_line(record: _AtomRecord, serial: int) -> str:
    return f"{record.line[:6]}{serial:5d}{record.line[11:]}"

class ResolveResidueAxisImplementation:
    """Resolve one admitted structure into its canonical residue axis."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        inputs = call.inputs
        with self._run_resources.engine_invocation():
            return {
                "residue_axis": resolve_residue_axis(
                    inputs["structure"].value,
                    (
                        inputs["modified_residue_normalizations"].value
                        if "modified_residue_normalizations" in inputs
                        else None
                    ),
                )
            }
