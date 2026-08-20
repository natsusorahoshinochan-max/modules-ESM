"""Provider-free, canonical structure conversions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import re
from typing import Any, ClassVar, Mapping

from core import OperationCall, RunResources, builtin_frozen_catalog
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ResolvedStructureResidueAxis,
    StructureAtomCoordinate,
    StructureAxisSegment,
    StructureComponentDisposition,
    StructureResidueCoordinates,
)

from .domain import (
    CandidateNormalizationFact,
    CandidateNormalizationFactCollection,
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
    normalization_key,
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
_STRUCTURE_CONTENT_TYPE = builtin_frozen_catalog().require_port_type(
    "protein.structure",
    "4.0.0",
)

_CSH_PARENT_ATOMS = (
    ("SER", "S", (
        ("N1", "N"),
        ("CA1", "CA"),
        ("C1", "C"),
        ("CB1", "CB"),
        ("OG2", "OG"),
    )),
    ("HIS", "H", (
        ("N2", "N"),
        ("CA2", "CA"),
        ("C2", "C"),
        ("O2", "O"),
        ("CB2", "CB"),
        ("CG", "CG"),
        ("CD2", "CD2"),
        ("ND1", "ND1"),
        ("CE1", "CE1"),
        ("NE2", "NE2"),
    )),
    ("GLY", "G", (
        ("N3", "N"),
        ("CA3", "CA"),
        ("C3", "C"),
        ("O3", "O"),
    )),
)


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
    if type(structure) is not ProteinStructure:
        raise ValueError("residue-axis resolution requires a ProteinStructure")
    if normalizations is None:
        supplied_normalizations = ModifiedResidueNormalizationCollection()
    elif type(normalizations) is ModifiedResidueNormalizationCollection:
        supplied_normalizations = normalizations
    else:
        raise ValueError("modified-residue normalizations have the wrong type")

    modres, seqres = _pdb_polymer_declarations(structure)
    components = _coordinate_components(structure)
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


def _parent_atom_line(
    record: _AtomRecord,
    *,
    serial: int,
    residue_name: str,
    residue_number: int,
    atom_name: str,
) -> str:
    line = list(record.line)
    line[0:6] = "ATOM  "
    line[6:11] = f"{serial:5d}"
    line[12:16] = f" {atom_name:<3}"
    line[16] = " "
    line[17:20] = f"{residue_name:>3}"
    line[22:26] = f"{residue_number:4d}"
    line[26] = " "
    return "".join(line)


def _canonical_seqres_lines(
    chain_id: str,
    components: tuple[str, ...],
) -> tuple[str, ...]:
    if len(components) > 9999:
        raise ValueError("normalized CSH SEQRES residue count exceeds PDB limits")
    return tuple(
        (
            f"SEQRES {serial:3d} {chain_id} {len(components):4d}  "
            + " ".join(components[offset : offset + 13])
        ).ljust(80)
        for serial, offset in enumerate(range(0, len(components), 13), start=1)
    )


def _normalized_csh_polymer_declarations(
    structure: ProteinStructure,
    normalized_identities: set[tuple[str, str, str]],
) -> list[str]:
    _, seqres = _pdb_polymer_declarations(structure)
    normalized_count_by_chain: dict[str, int] = defaultdict(int)
    for chain_id, _, _ in normalized_identities:
        normalized_count_by_chain[chain_id] += 1

    seqres_rewrites: dict[str, tuple[str, ...]] = {}
    for chain_id, normalized_count in normalized_count_by_chain.items():
        components = seqres.get(chain_id)
        if components is None or "CSH" not in components:
            continue
        if components.count("CSH") != normalized_count:
            raise ValueError(
                "CSH SEQRES correspondence does not match normalized "
                f"components in chain {chain_id}"
            )
        normalized_components = tuple(
            parent_component
            for component in components
            for parent_component in (
                ("SER", "HIS", "GLY")
                if component == "CSH"
                else (component,)
            )
        )
        seqres_rewrites[chain_id] = _canonical_seqres_lines(
            chain_id,
            normalized_components,
        )

    declarations: list[str] = []
    emitted_seqres_chains: set[str] = set()
    for line in structure.pdb_string.splitlines():
        if line.startswith("MODRES"):
            identity = (line[16], line[18:22].strip(), line[22].strip())
            if identity in normalized_identities:
                if line[12:15].strip().upper() != "CSH":
                    raise ValueError(
                        "CSH coordinate component contradicts its MODRES "
                        "declaration"
                    )
                continue
            declarations.append(line)
            continue
        if not line.startswith("SEQRES"):
            continue
        chain_id = line[11]
        rewrite = seqres_rewrites.get(chain_id)
        if rewrite is None:
            declarations.append(line)
            continue
        if chain_id not in emitted_seqres_chains:
            declarations.extend(rewrite)
            emitted_seqres_chains.add(chain_id)
    return declarations


def normalize_csh_parent_span(
    structure: ProteinStructure,
) -> tuple[ProteinStructure, ModifiedResidueNormalizationCollection]:
    """Expand each exact CSH component into its SER-HIS-GLY parents."""
    records = _single_model_records(structure)
    coordinate_records = [
        record for record in records if record is not None
    ]
    csh_groups: dict[tuple[str, str, str], list[_AtomRecord]] = {}
    for record in coordinate_records:
        if record.residue_name == "CSH":
            csh_groups.setdefault(record.residue_identity, []).append(record)
    if not csh_groups:
        raise ValueError("structure contains no CSH component to normalize")
    for identity in csh_groups:
        positions = [
            index
            for index, record in enumerate(records)
            if record is not None
            and record.residue_identity == identity
            and record.residue_name == "CSH"
        ]
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise ValueError("CSH component coordinate records are noncontiguous")

    occupied = {
        record.residue_identity
        for record in coordinate_records
        if record.residue_name != "CSH"
    }
    replacements: dict[
        tuple[str, str, str],
        tuple[list[tuple[_AtomRecord, str, int, str]], ModifiedResidueNormalization],
    ] = {}
    expected_source_atoms = {
        source_atom
        for _, _, atoms in _CSH_PARENT_ATOMS
        for source_atom, _ in atoms
    }
    for identity, component_records in csh_groups.items():
        representative = component_records[0]
        if representative.insertion_code:
            raise ValueError(
                "CSH normalization does not accept insertion-coded components"
            )
        try:
            observed_number = int(representative.residue_number)
        except ValueError as error:
            raise ValueError("CSH residue number must be an integer") from error
        by_atom: dict[str, _AtomRecord] = {}
        for record in component_records:
            if record.record != "HETATM" or record.altloc != " ":
                raise ValueError(
                    "CSH normalization requires unambiguous HETATM records"
                )
            if record.atom_name in by_atom:
                raise ValueError(
                    f"CSH {record.public_residue_id} has duplicate atom "
                    f"{record.atom_name}"
                )
            by_atom[record.atom_name] = record
        if set(by_atom) != expected_source_atoms:
            missing = sorted(expected_source_atoms - set(by_atom))
            unexpected = sorted(set(by_atom) - expected_source_atoms)
            raise ValueError(
                "CSH atom inventory does not match the exact parent mapping; "
                f"missing={missing}, unexpected={unexpected}"
            )

        parent_ids = tuple(
            f"{representative.chain_id}:{observed_number + offset}"
            for offset in (-1, 0, 1)
        )
        collisions = [
            parent_id
            for parent_id, offset in zip(parent_ids, (-1, 0, 1), strict=True)
            if (
                representative.chain_id,
                str(observed_number + offset),
                "",
            ) in occupied
        ]
        if collisions:
            raise ValueError(
                "CSH parent residues collide with existing coordinates: "
                + ", ".join(collisions)
            )

        output_atoms: list[tuple[_AtomRecord, str, int, str]] = []
        atom_mappings: list[ModifiedResidueAtomMapping] = []
        for parent_index, (residue_name, _, atom_pairs) in enumerate(
            _CSH_PARENT_ATOMS
        ):
            parent_number = observed_number + parent_index - 1
            parent_id = parent_ids[parent_index]
            for source_atom, parent_atom in atom_pairs:
                output_atoms.append(
                    (
                        by_atom[source_atom],
                        residue_name,
                        parent_number,
                        parent_atom,
                    )
                )
                atom_mappings.append(
                    ModifiedResidueAtomMapping(
                        source_atom_name=source_atom,
                        parent_residue_id=parent_id,
                        parent_atom_name=parent_atom,
                    )
                )
        replacements[identity] = (
            output_atoms,
            ModifiedResidueNormalization(
                component_id="CSH",
                observed_residue_id=representative.public_residue_id,
                parent_residue_ids=parent_ids,
                parent_sequence="SHG",
                atom_mappings=tuple(atom_mappings),
            ),
        )

    output_lines = _normalized_csh_polymer_declarations(
        structure,
        set(replacements),
    )
    normalizations: list[ModifiedResidueNormalization] = []
    emitted: set[tuple[str, str, str]] = set()
    serial = 1
    for record_index, record in enumerate(records):
        if record is None:
            previous = records[record_index - 1]
            following = records[record_index + 1]
            assert previous is not None and following is not None
            previous_number = int(previous.residue_number)
            following_number = int(following.residue_number)
            following_is_replaced = following.residue_identity in replacements
            previous_is_replaced = previous.residue_identity in replacements
            bridges_parent_span = (
                previous.chain_id == following.chain_id
                and not previous.insertion_code
                and not following.insertion_code
                and (
                    (
                        following_is_replaced
                        and previous.record == "ATOM  "
                        and previous_number == following_number - 2
                    )
                    or (
                        previous_is_replaced
                        and following.record == "ATOM  "
                        and following_number == previous_number + 2
                    )
                )
            )
            if bridges_parent_span:
                continue
            if output_lines and output_lines[-1] != "TER":
                output_lines.append("TER")
            continue
        replacement = replacements.get(record.residue_identity)
        if replacement is None:
            output_lines.append(_renumbered_atom_line(record, serial))
            serial += 1
            continue
        if record.residue_identity in emitted:
            continue
        emitted.add(record.residue_identity)
        output_atoms, normalization = replacement
        for source, residue_name, residue_number, atom_name in output_atoms:
            output_lines.append(
                _parent_atom_line(
                    source,
                    serial=serial,
                    residue_name=residue_name,
                    residue_number=residue_number,
                    atom_name=atom_name,
                )
            )
            serial += 1
        normalizations.append(normalization)
    output_lines.append("END")
    return (
        ProteinStructure(
            pdb_string="\n".join(output_lines) + "\n",
        ),
        ModifiedResidueNormalizationCollection(entries=normalizations),
    )


def select_chains(
    structure: ProteinStructure,
    chain_ids: object,
) -> ProteinStructure:
    """Select exact chain identities and emit them in request order."""
    if (
        not isinstance(chain_ids, (list, tuple))
        or not chain_ids
        or any(
            type(chain_id) is not str
            or len(chain_id) != 1
            or not chain_id.isascii()
            or not chain_id.isalnum()
            for chain_id in chain_ids
        )
        or len(set(chain_ids)) != len(chain_ids)
    ):
        raise ValueError("chain_ids must be an ordered nonempty unique list")
    segments = _coordinate_segments(_single_model_records(structure))
    available = {segment[0].chain_id for segment in segments}
    missing = [chain_id for chain_id in chain_ids if chain_id not in available]
    if missing:
        raise ValueError(
            "requested chains are absent: " + ", ".join(missing)
        )
    declaration_lines: dict[str, list[str]] = defaultdict(list)
    for line in structure.pdb_string.splitlines():
        if line.startswith("SEQRES"):
            if len(line) < 12:
                raise ValueError("PDB SEQRES record has no chain identity")
            declaration_lines[line[11]].append(line)
        elif line.startswith("MODRES"):
            if len(line) < 17:
                raise ValueError("PDB MODRES record has no chain identity")
            declaration_lines[line[16]].append(line)
    output_lines = [
        line
        for chain_id in chain_ids
        for line in declaration_lines.get(chain_id, ())
    ]
    serial = 1
    for chain_id in chain_ids:
        for segment in segments:
            if segment[0].chain_id != chain_id:
                continue
            for record in segment:
                output_lines.append(_renumbered_atom_line(record, serial))
                serial += 1
            output_lines.append("TER")
    if not output_lines:
        raise ValueError("chain selection produced no coordinate records")
    output_lines.append("END")
    return ProteinStructure(
        pdb_string="\n".join(output_lines) + "\n",
    )


def _axis_residue_pdb_identity(residue_id: str) -> tuple[str, str, str]:
    match = re.fullmatch(
        r"(?P<chain>[A-Za-z0-9]):"
        r"(?P<number>[+-]?[0-9]{1,4})(?P<insertion>[A-Za-z]?)",
        residue_id,
    )
    if match is None or len(match.group("number")) > 4:
        raise ValueError(
            f"resolved residue identity {residue_id!r} cannot be written "
            "to canonical PDB"
        )
    return (
        match.group("chain"),
        match.group("number"),
        match.group("insertion"),
    )


def _axis_backbone_line(
    *,
    serial: int,
    atom_name: str,
    residue_name: str,
    residue_id: str,
    coordinate: tuple[float, float, float],
) -> str:
    chain_id, residue_number, insertion_code = _axis_residue_pdb_identity(
        residue_id
    )
    element = {
        "N": "N",
        "CA": "C",
        "C": "C",
        "O": "O",
    }[atom_name]
    return (
        f"ATOM  {serial:5d} {atom_name:^4} "
        f"{residue_name:>3} {chain_id}{residue_number:>4}"
        f"{insertion_code or ' '}   "
        f"{coordinate[0]:8.3f}{coordinate[1]:8.3f}{coordinate[2]:8.3f}"
        f"{1.0:6.2f}{0.0:6.2f}          {element:>2}  "
    )


def extract_backbone(
    residue_axis: ResolvedStructureResidueAxis,
) -> ProteinStructure:
    """Project canonical N/CA/C/O records from one resolved residue axis."""
    if type(residue_axis) is not ResolvedStructureResidueAxis:
        raise ValueError(
            "backbone extraction requires a ResolvedStructureResidueAxis"
        )
    incomplete = tuple(
        residue_id
        for residue_id, is_complete in zip(
            residue_axis.layout.residue_ids,
            residue_axis.complete_backbone_mask,
            strict=True,
        )
        if not is_complete
    )
    if incomplete:
        raise ValueError(
            "resolved residues lack backbone atoms: " + ", ".join(incomplete)
        )
    residue_names_by_id = dict(
        zip(
            residue_axis.layout.residue_ids,
            residue_axis.residue_names,
            strict=True,
        )
    )
    output_lines: list[str] = []
    serial = 1
    for segment in residue_axis.segments:
        for residue_id in segment.residue_ids:
            backbone_coordinates = residue_axis.backbone_coordinates_for(
                residue_id
            )
            for atom_name in _BACKBONE_ATOMS:
                output_lines.append(
                    _axis_backbone_line(
                        serial=serial,
                        atom_name=atom_name,
                        residue_name=residue_names_by_id[residue_id],
                        residue_id=residue_id,
                        coordinate=backbone_coordinates[atom_name],
                    )
                )
                serial += 1
        output_lines.append("TER")
    output_lines.append("END")
    backbone = ProteinStructure(
        pdb_string="\n".join(output_lines) + "\n",
    )
    validate_backbone_structure(backbone)
    return backbone


def extract_sequence(
    residue_axis: ResolvedStructureResidueAxis,
) -> ProteinSequence:
    """Project the exact parent sequence and identities from a resolved axis."""
    if type(residue_axis) is not ResolvedStructureResidueAxis:
        raise ValueError(
            "sequence extraction requires a ResolvedStructureResidueAxis"
        )
    return ProteinSequence(
        sequence=residue_axis.sequence,
        residue_ids=residue_axis.layout.residue_ids,
    )


def _structure_candidate_parents(value: object) -> list[Candidate]:
    if (
        type(value) is not CandidateCollection
        or value.item_type != "protein.structure"
        or not value.items
    ):
        raise ValueError(
            "Candidate-aware structure transformation requires non-empty "
            "protein structure Candidates"
        )
    parents: list[Candidate] = []
    parent_ids: set[str] = set()
    for parent in value.items:
        if (
            type(parent) is not Candidate
            or type(parent.data) is not ProteinStructure
            or not parent.candidate_id
            or parent.candidate_id in parent_ids
        ):
            raise ValueError(
                "structure Candidates contain incomplete or duplicate parents"
            )
        parent_ids.add(parent.candidate_id)
        parents.append(parent)
    return parents


def _candidate_structures_and_references(
    call: OperationCall,
) -> tuple[tuple[Candidate, CandidateDataReference], ...]:
    admitted = call.inputs.get("structure_candidates")
    collection = None if admitted is None else admitted.value
    if (
        type(collection) is not CandidateCollection
        or collection.item_type != "protein.structure"
        or not collection.items
    ):
        raise ValueError(
            "structure_candidates must be a nonempty protein.structure "
            "CandidateCollection"
        )
    candidates_by_id: dict[str, Candidate] = {}
    for candidate in collection.items:
        if (
            type(candidate) is not Candidate
            or type(candidate.data) is not ProteinStructure
            or not candidate.candidate_id
            or candidate.candidate_id in candidates_by_id
        ):
            raise ValueError(
                "Candidate structure association requires complete exact "
                "Candidate references"
            )
        candidates_by_id[candidate.candidate_id] = candidate

    references_by_id = {
        reference.candidate_id: reference
        for reference in admitted.candidate_data
    }

    pairs: list[tuple[Candidate, CandidateDataReference]] = []
    for candidate in collection.items:
        reference = references_by_id[candidate.candidate_id]
        pairs.append((candidate, reference))
    return tuple(pairs)


def _candidate_normalizations_by_id(
    value: object,
    references_by_id: Mapping[str, CandidateDataReference],
) -> dict[str, ModifiedResidueNormalizationCollection]:
    if type(value) is not CandidateModifiedResidueNormalizationAssociations:
        raise ValueError(
            "Candidate residue-axis resolution requires complete exact "
            "Candidate references for modified-residue normalizations"
        )
    entries_by_id: dict[
        str,
        CandidateModifiedResidueNormalizationAssociation,
    ] = {}
    for entry in value.entries:
        if (
            type(entry)
            is not CandidateModifiedResidueNormalizationAssociation
            or entry.subject.candidate_id in entries_by_id
        ):
            raise ValueError(
                "Candidate residue-axis resolution requires complete exact "
                "Candidate references for modified-residue normalizations"
            )
        entries_by_id[entry.subject.candidate_id] = entry
    if set(entries_by_id) != set(references_by_id) or any(
        entries_by_id[candidate_id].subject != reference
        for candidate_id, reference in references_by_id.items()
    ):
        raise ValueError(
            "Candidate residue-axis resolution requires complete exact "
            "Candidate references for modified-residue normalizations"
        )
    return {
        candidate_id: entries_by_id[candidate_id].normalizations
        for candidate_id in references_by_id
    }


def validate_backbone_structure(value: object) -> None:
    """Validate the exact canonical backbone-only nominal value."""
    if type(value) is not ProteinStructure:
        raise ValueError("backbone must be a ProteinStructure")
    _STRUCTURE_CONTENT_TYPE.validate(value)
    text = value.pdb_string
    if not text.endswith("\n") or "\r" in text or "\n\n" in text:
        raise ValueError("backbone PDB text is not canonical LF text")
    lines = text.splitlines()
    if not lines or lines[-1] != "END" or lines.count("END") != 1:
        raise ValueError("backbone must end with exactly one END record")
    coordinate_lines = [
        line for line in lines if line.startswith("ATOM  ")
    ]
    if not coordinate_lines:
        raise ValueError("backbone contains no ATOM records")
    if any(
        not (
            line.startswith("ATOM  ")
            or line == "TER"
            or line == "END"
        )
        for line in lines
    ):
        raise ValueError("backbone contains a noncanonical record")
    if any(line.startswith("HETATM") for line in lines):
        raise ValueError("backbone cannot contain HETATM records")
    records: list[_AtomRecord] = []
    current_chain: str | None = None
    current_residue: tuple[str, str, str] | None = None
    current_residue_name: str | None = None
    expected_atom_index = 0
    segment_has_atoms = False
    for line in lines[:-1]:
        if line.startswith("ATOM  "):
            record = _atom_record(line)
            records.append(record)
            if record.altloc != " ":
                raise ValueError(
                    "backbone alternate-location markers must be resolved"
                )
            if current_chain is None:
                current_chain = record.chain_id
            elif record.chain_id != current_chain:
                raise ValueError(
                    "backbone chain changes must be separated by TER"
                )
            if current_residue != record.residue_identity:
                if current_residue is not None and (
                    expected_atom_index != len(_BACKBONE_ATOMS)
                ):
                    raise ValueError(
                        "backbone TER or residue boundary split a residue"
                    )
                current_residue = record.residue_identity
                current_residue_name = record.residue_name
                expected_atom_index = 0
            elif record.residue_name != current_residue_name:
                raise ValueError(
                    "backbone residue atoms have conflicting residue names"
                )
            if (
                expected_atom_index >= len(_BACKBONE_ATOMS)
                or record.atom_name
                != _BACKBONE_ATOMS[expected_atom_index]
            ):
                raise ValueError(
                    "every backbone residue must contain N, CA, C, O"
                )
            expected_atom_index += 1
            segment_has_atoms = True
            continue
        if line == "TER":
            if (
                not segment_has_atoms
                or current_residue is None
                or expected_atom_index != len(_BACKBONE_ATOMS)
            ):
                raise ValueError("backbone contains an empty chain segment")
            current_chain = None
            current_residue = None
            current_residue_name = None
            expected_atom_index = 0
            segment_has_atoms = False
    if current_chain is not None or segment_has_atoms:
        raise ValueError("every backbone segment must terminate with TER")
    serials = [int(record.line[6:11]) for record in records]
    if serials != list(range(1, len(records) + 1)):
        raise ValueError("backbone atom serials must be canonical")


class StructureTransformImplementation:
    """One cohesive executor selected by the exact Node Binding."""

    _operation: ClassVar[str]

    def __init__(self, run_resources: RunResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        inputs = call.inputs
        node_parameters = call.node_parameters
        binding_parameters = call.binding_parameters
        if self._operation == "normalize_csh_parent_span_candidates":
            if (
                binding_parameters
                or node_parameters
                or set(inputs) != {"structure_candidates"}
            ):
                raise ValueError(
                    "Candidate CSH normalization inputs are invalid"
                )
            candidates_and_references = _candidate_structures_and_references(call)
            normalized_candidates = []
            facts = []
            from .port_types import (
                MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
            )

            with self._run_resources.engine_invocation():
                for output_slot, (candidate, _) in enumerate(
                    candidates_and_references
                ):
                    normalized, normalizations = normalize_csh_parent_span(
                        candidate.data
                    )
                    structure_digest = _STRUCTURE_CONTENT_TYPE.content_digest(
                        normalized
                    )
                    normalizations_digest = (
                        MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE.content_digest(
                            normalizations
                        )
                    )
                    key = normalization_key(
                        output_role="structure_candidates",
                        output_slot=output_slot,
                        structure_content_digest=structure_digest,
                        normalizations_content_digest=normalizations_digest,
                    )
                    normalized_candidates.append(
                        Candidate(
                            candidate_id=f"normalized-csh-{output_slot}",
                            data=normalized,
                            parent_ids=(candidate.candidate_id,),
                            metadata={
                                "transform": (
                                    "structure_transform."
                                    "normalize_csh_parent_span_candidates"
                                ),
                                "normalization_key": key,
                            },
                        )
                    )
                    facts.append(
                        CandidateNormalizationFact(
                            normalization_key=key,
                            structure_content_digest=structure_digest,
                            normalizations=normalizations,
                        )
                    )
            result = {
                "structure_candidates": CandidateCollection(
                    collection_id="normalized-csh-structure-candidates",
                    item_type="protein.structure",
                    items=tuple(normalized_candidates),
                ),
                "normalization_facts": CandidateNormalizationFactCollection(
                    tuple(facts)
                ),
            }
            return result
        if self._operation == "materialize_candidate_normalizations":
            if (
                binding_parameters
                or node_parameters
                or set(inputs)
                != {"structure_candidates", "normalization_facts"}
            ):
                raise ValueError(
                    "Candidate normalization materialization inputs are invalid"
                )
            candidates_and_references = _candidate_structures_and_references(call)
            facts = inputs["normalization_facts"].value
            if type(facts) is not CandidateNormalizationFactCollection:
                raise ValueError(
                    "normalization_facts must be an exact admitted collection"
                )
            facts_by_key = {
                fact.normalization_key: fact for fact in facts.entries
            }
            candidate_keys = {
                candidate.metadata.get("normalization_key")
                for candidate, _ in candidates_and_references
            }
            if (
                None in candidate_keys
                or len(candidate_keys) != len(candidates_and_references)
                or candidate_keys != set(facts_by_key)
            ):
                raise ValueError(
                    "Candidates and normalization facts must form one complete key set"
                )
            with self._run_resources.engine_invocation():
                associations = []
                for output_slot, (candidate, reference) in enumerate(
                    candidates_and_references
                ):
                    key = candidate.metadata["normalization_key"]
                    assert type(key) is str
                    fact = facts_by_key[key]
                    output_port = candidate.metadata.get("output_port")
                    sample_slot = candidate.metadata.get("sample_slot")
                    if output_port != "structure_candidates" or sample_slot != (
                        f"0:{output_slot}"
                    ):
                        raise ValueError(
                            "normalized Candidate output slot metadata is incomplete"
                        )
                    from .port_types import (
                        MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE,
                    )

                    expected_key = normalization_key(
                        output_role=output_port,
                        output_slot=output_slot,
                        structure_content_digest=reference.content_digest,
                        normalizations_content_digest=(
                            MODIFIED_RESIDUE_NORMALIZATIONS_PORT_TYPE.content_digest(
                                fact.normalizations
                            )
                        ),
                    )
                    if (
                        fact.structure_content_digest != reference.content_digest
                        or key != expected_key
                    ):
                        raise ValueError(
                            "normalization fact contradicts admitted Candidate content"
                        )
                    associations.append(
                        CandidateModifiedResidueNormalizationAssociation(
                            subject=reference,
                            normalizations=fact.normalizations,
                        )
                    )
            return {
                "modified_residue_normalizations": (
                    CandidateModifiedResidueNormalizationAssociations(
                        tuple(associations)
                    )
                )
            }
        if self._operation == "project_single_residue_axis":
            if (
                binding_parameters
                or node_parameters
                or set(inputs) != {"structure_candidates", "residue_axes"}
            ):
                raise ValueError("single residue-axis projection inputs are invalid")
            candidates_and_references = _candidate_structures_and_references(call)
            axes = inputs["residue_axes"].value
            if (
                len(candidates_and_references) != 1
                or type(axes) is not CandidateResolvedResidueAxisAssociations
                or len(axes.entries) != 1
                or axes.entries[0].subject != candidates_and_references[0][1]
            ):
                raise ValueError(
                    "single residue-axis projection requires one exact association"
                )
            with self._run_resources.engine_invocation():
                return {"residue_axis": axes.entries[0].residue_axis}
        if self._operation == "extract_sequence_candidates":
            if (
                binding_parameters
                or node_parameters
                or set(inputs) != {"structure_candidates", "residue_axes"}
            ):
                raise ValueError(
                    "Candidate sequence extraction inputs are invalid"
                )
            candidates_and_references = _candidate_structures_and_references(
                call
            )
            residue_axes = inputs["residue_axes"].value
            if (
                type(residue_axes)
                is not CandidateResolvedResidueAxisAssociations
            ):
                raise ValueError(
                    "Candidate sequence extraction requires exact-reference "
                    "resolved residue-axis associations"
                )
            axes_by_id = {
                entry.subject.candidate_id: entry
                for entry in residue_axes.entries
            }
            references_by_id = {
                reference.candidate_id: reference
                for _, reference in candidates_and_references
            }
            if set(axes_by_id) != set(references_by_id) or any(
                axes_by_id[candidate_id].subject != reference
                for candidate_id, reference in references_by_id.items()
            ):
                raise ValueError(
                    "Candidate sequence extraction requires complete exact "
                    "Candidate references"
                )
            with self._run_resources.engine_invocation():
                return {
                    "sequence_candidates": CandidateCollection(
                        collection_id="extracted-sequence-candidates",
                        item_type="protein.sequence",
                        items=tuple(
                            Candidate(
                                candidate_id=f"extracted-sequence-{index}",
                                data=extract_sequence(
                                    axes_by_id[
                                        reference.candidate_id
                                    ].residue_axis
                                ),
                                parent_ids=[candidate.candidate_id],
                                metadata={
                                    "transform": (
                                        "structure_transform."
                                        "extract_sequence_candidates"
                                    ),
                                    "parent_index": index,
                                },
                            )
                            for index, (candidate, reference) in enumerate(
                                candidates_and_references
                            )
                        ),
                    )
                }
        if self._operation == "resolve_candidate_residue_axes":
            if (
                binding_parameters
                or node_parameters
                or set(inputs)
                not in (
                    {"structure_candidates"},
                    {
                        "structure_candidates",
                        "modified_residue_normalizations",
                    },
                )
            ):
                raise ValueError(
                    "Candidate residue-axis resolution inputs are invalid"
                )
            candidates_and_references = _candidate_structures_and_references(
                call
            )
            references_by_id = {
                reference.candidate_id: reference
                for _, reference in candidates_and_references
            }
            normalizations_by_id = (
                _candidate_normalizations_by_id(
                    inputs["modified_residue_normalizations"].value,
                    references_by_id,
                )
                if "modified_residue_normalizations" in inputs
                else {}
            )
            with self._run_resources.engine_invocation():
                return {
                    "residue_axes": CandidateResolvedResidueAxisAssociations(
                        entries=tuple(
                            CandidateResolvedResidueAxisAssociation(
                                subject=reference,
                                residue_axis=resolve_residue_axis(
                                    candidate.data,
                                    normalizations_by_id.get(
                                        candidate.candidate_id
                                    ),
                                ),
                            )
                            for candidate, reference
                            in candidates_and_references
                        )
                    )
                }
        if self._operation == "resolve_residue_axis":
            if (
                binding_parameters
                or node_parameters
                or set(inputs)
                not in (
                    {"structure"},
                    {"structure", "modified_residue_normalizations"},
                )
            ):
                raise ValueError(
                    "residue-axis resolution inputs are invalid"
                )
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
        if self._operation == "backbone_to_structure":
            expected_input = "backbone"
        elif self._operation == "select_candidate_chains":
            expected_input = "structure_candidates"
        elif self._operation in {"extract_backbone", "extract_sequence"}:
            expected_input = "residue_axis"
        else:
            expected_input = "structure"
        if binding_parameters or set(inputs) != {expected_input}:
            raise ValueError(
                "structure transform requires exactly one declared input"
            )
        structure = inputs[expected_input].value
        expected_parameters = (
            {"chain_ids"}
            if self._operation in {
                "select_chains",
                "select_candidate_chains",
            }
            else set()
        )
        if set(node_parameters) != expected_parameters:
            raise ValueError("structure transform parameters are invalid")
        with self._run_resources.engine_invocation():
            if self._operation == "select_chains":
                return {
                    "structure": select_chains(
                        structure,
                        node_parameters["chain_ids"],
                    )
                }
            if self._operation == "extract_backbone":
                return {"backbone": extract_backbone(structure)}
            if self._operation == "extract_sequence":
                return {"sequence": extract_sequence(structure)}
            if self._operation == "normalize_csh_parent_span":
                normalized, normalizations = normalize_csh_parent_span(
                    structure
                )
                return {
                    "structure": normalized,
                    "modified_residue_normalizations": normalizations,
                }
            if self._operation == "select_candidate_chains":
                children = []
                for index, parent in enumerate(
                    _structure_candidate_parents(structure)
                ):
                    children.append(
                        Candidate(
                            candidate_id=f"selected-structure-{index}",
                            data=select_chains(
                                parent.data,
                                node_parameters["chain_ids"],
                            ),
                            parent_ids=[parent.candidate_id],
                            metadata={
                                "transform": (
                                    "structure_transform."
                                    "select_candidate_chains"
                                ),
                                "parent_index": index,
                                "chain_ids": list(
                                    node_parameters["chain_ids"]
                                ),
                            },
                        )
                    )
                return {
                    "structure_candidates": CandidateCollection(
                        collection_id="selected-structure-candidates",
                        item_type="protein.structure",
                        items=children,
                    )
                }
            if self._operation == "backbone_to_structure":
                if type(structure) is not ProteinStructure:
                    raise ValueError(
                        "backbone bridge requires a ProteinStructure"
                    )
                return {
                    "structure": ProteinStructure(
                        pdb_string=structure.pdb_string,
                    )
                }
        raise ValueError("unknown structure transform operation")


class SelectChainsImplementation(StructureTransformImplementation):
    _operation = "select_chains"


class SelectCandidateChainsImplementation(StructureTransformImplementation):
    _operation = "select_candidate_chains"


class ExtractBackboneImplementation(StructureTransformImplementation):
    _operation = "extract_backbone"


class ExtractSequenceImplementation(StructureTransformImplementation):
    _operation = "extract_sequence"


class ExtractSequenceCandidatesImplementation(
    StructureTransformImplementation
):
    _operation = "extract_sequence_candidates"


class NormalizeCshParentSpanImplementation(
    StructureTransformImplementation
):
    _operation = "normalize_csh_parent_span"


class NormalizeCshParentSpanCandidatesImplementation(
    StructureTransformImplementation
):
    _operation = "normalize_csh_parent_span_candidates"


class MaterializeCandidateNormalizationsImplementation(
    StructureTransformImplementation
):
    _operation = "materialize_candidate_normalizations"


class ProjectSingleResidueAxisImplementation(StructureTransformImplementation):
    _operation = "project_single_residue_axis"


class ResolveResidueAxisImplementation(StructureTransformImplementation):
    _operation = "resolve_residue_axis"


class ResolveCandidateResidueAxesImplementation(
    StructureTransformImplementation
):
    _operation = "resolve_candidate_residue_axes"


class BackboneToStructureImplementation(StructureTransformImplementation):
    _operation = "backbone_to_structure"
