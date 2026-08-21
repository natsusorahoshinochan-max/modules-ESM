"""Canonical chain, backbone, and sequence projections."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import cast

from core.catalog.builtins import (
    builtin_frozen_catalog,
)
from core.operation import (
    OperationResources,
    OperationCall,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure, ResolvedStructureResidueAxis

from .residue_axis import (
    _AtomRecord,
    _BACKBONE_ATOMS,
    _atom_record,
    _coordinate_segments,
    _renumbered_atom_line,
    _single_model_records,
)


_STRUCTURE_CONTENT_TYPE = builtin_frozen_catalog().require_port_type(
    "protein.structure",
    "4.0.0",
)


def select_chains(
    structure: ProteinStructure,
    chain_ids: object,
) -> ProteinStructure:
    """Select exact chain identities and emit them in request order."""
    admitted_chain_ids = cast(tuple[str, ...], chain_ids)
    segments = _coordinate_segments(_single_model_records(structure))
    available = {segment[0].chain_id for segment in segments}
    missing = [
        chain_id for chain_id in admitted_chain_ids if chain_id not in available
    ]
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
        for chain_id in admitted_chain_ids
        for line in declaration_lines.get(chain_id, ())
    ]
    serial = 1
    for chain_id in admitted_chain_ids:
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
    return backbone


def extract_sequence(
    residue_axis: ResolvedStructureResidueAxis,
) -> ProteinSequence:
    """Project the exact parent sequence and identities from a resolved axis."""
    return ProteinSequence(
        sequence=residue_axis.sequence,
        residue_ids=residue_axis.layout.residue_ids,
    )


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

class SelectChainsImplementation:
    """Project admitted chains in the exact requested order."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        with self._run_resources.engine_invocation():
            return {
                "structure": select_chains(
                    call.inputs["structure"].value,
                    call.node_parameters["chain_ids"],
                )
            }


class ExtractBackboneImplementation:
    """Project a canonical backbone from one resolved residue axis."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        with self._run_resources.engine_invocation():
            return {
                "backbone": extract_backbone(
                    call.inputs["residue_axis"].value
                )
            }


class ExtractSequenceImplementation:
    """Project sequence identities from one resolved residue axis."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        with self._run_resources.engine_invocation():
            return {
                "sequence": extract_sequence(
                    call.inputs["residue_axis"].value
                )
            }


class BackboneToStructureImplementation:
    """Convert canonical backbone nominal data to generic structure data."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        backbone = call.inputs["backbone"].value
        with self._run_resources.engine_invocation():
            return {
                "structure": ProteinStructure(
                    pdb_string=backbone.pdb_string,
                )
            }
