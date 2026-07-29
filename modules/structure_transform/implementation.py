"""Provider-free, canonical structure conversions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping

from datatypes import ProteinSequence, ProteinStructure


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
    if len(line) < 54:
        raise ValueError("PDB coordinate record is shorter than 54 columns")
    record = line[:6]
    chain_id = line[21]
    residue_number = line[22:26].strip()
    if (
        record not in {"ATOM  ", "HETATM"}
        or chain_id == " "
        or not chain_id.isascii()
        or not chain_id.isalnum()
        or not residue_number
    ):
        raise ValueError("PDB coordinate identity is invalid")
    try:
        int(residue_number)
        float(line[30:38])
        float(line[38:46])
        float(line[46:54])
    except ValueError as error:
        raise ValueError("PDB coordinate record is malformed") from error
    return _AtomRecord(
        line=line.rstrip(),
        record=record,
        atom_name=line[12:16].strip(),
        altloc=line[16],
        residue_name=line[17:20].strip(),
        chain_id=chain_id,
        residue_number=residue_number,
        insertion_code=line[26].strip(),
    )


def _single_model_records(structure: object) -> list[_AtomRecord | None]:
    if type(structure) is not ProteinStructure:
        raise ValueError("structure must be a ProteinStructure")
    text = structure.pdb_string
    if not text or "\r" in text:
        raise ValueError("structure must use nonempty canonical LF PDB text")
    lines = text.splitlines()
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


def _segments(
    records: list[_AtomRecord | None],
    *,
    atom_only: bool,
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
        if atom_only and record.record != "ATOM  ":
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


def _renumbered_atom_line(record: _AtomRecord, serial: int) -> str:
    line = record.line.ljust(80)
    return f"{line[:6]}{serial:5d}{line[11:]}".rstrip()


def _normalized_backbone_atom_line(
    record: _AtomRecord,
    serial: int,
) -> str:
    line = _renumbered_atom_line(record, serial).ljust(80)
    return f"{line[:16]} {line[17:]}".rstrip()


def select_chains(
    structure: object,
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
    segments = _segments(
        _single_model_records(structure),
        atom_only=False,
    )
    available = {segment[0].chain_id for segment in segments}
    missing = [chain_id for chain_id in chain_ids if chain_id not in available]
    if missing:
        raise ValueError(
            "requested chains are absent: " + ", ".join(missing)
        )
    output_lines: list[str] = []
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
        source="structure_transform.select_chains",
    )


def extract_backbone(structure: object) -> ProteinStructure:
    """Retain one complete canonical N/CA/C/O set for every ATOM residue."""
    segments = _segments(
        _single_model_records(structure),
        atom_only=True,
    )
    if not segments:
        raise ValueError("structure contains no protein ATOM residues")
    output_lines: list[str] = []
    seen_residues: set[tuple[str, str, str]] = set()
    serial = 1
    for segment in segments:
        ordered_residues: list[
            tuple[tuple[str, str, str], list[_AtomRecord]]
        ] = []
        for record in segment:
            identity = record.residue_identity
            if not ordered_residues or ordered_residues[-1][0] != identity:
                if identity in seen_residues:
                    raise ValueError(
                        f"residue {record.public_residue_id} is noncontiguous"
                    )
                seen_residues.add(identity)
                ordered_residues.append((identity, []))
            ordered_residues[-1][1].append(record)
        for _, residue_records in ordered_residues:
            residue_names = {
                record.residue_name for record in residue_records
            }
            if len(residue_names) != 1:
                raise ValueError(
                    f"residue {residue_records[0].public_residue_id} "
                    "has conflicting residue names"
                )
            by_atom: dict[str, list[_AtomRecord]] = defaultdict(list)
            for record in residue_records:
                if record.atom_name in _BACKBONE_ATOMS:
                    by_atom[record.atom_name].append(record)
            missing = [
                atom_name
                for atom_name in _BACKBONE_ATOMS
                if atom_name not in by_atom
            ]
            residue_id = residue_records[0].public_residue_id
            if missing:
                raise ValueError(
                    f"residue {residue_id} lacks backbone atoms: "
                    + ", ".join(missing)
                )
            for atom_name in _BACKBONE_ATOMS:
                chosen = _choose_alternate(
                    by_atom[atom_name],
                    residue_id=residue_id,
                    atom_name=atom_name,
                )
                output_lines.append(
                    _normalized_backbone_atom_line(chosen, serial)
                )
                serial += 1
        output_lines.append("TER")
    output_lines.append("END")
    backbone = ProteinStructure(
        pdb_string="\n".join(output_lines) + "\n",
        source="structure_transform.extract_backbone",
    )
    validate_backbone_structure(backbone)
    return backbone


def extract_sequence(structure: object) -> ProteinSequence:
    """Derive ordered protein residues, ignoring HETATM non-protein records."""
    segments = _segments(
        _single_model_records(structure),
        atom_only=True,
    )
    residues: list[_AtomRecord] = []
    seen: set[tuple[str, str, str]] = set()
    for segment in segments:
        grouped: list[list[_AtomRecord]] = []
        for record in segment:
            if (
                not grouped
                or grouped[-1][0].residue_identity != record.residue_identity
            ):
                if record.residue_identity in seen:
                    raise ValueError(
                        f"residue {record.public_residue_id} is noncontiguous"
                    )
                seen.add(record.residue_identity)
                grouped.append([])
            grouped[-1].append(record)
        for residue_records in grouped:
            ca_records = [
                record
                for record in residue_records
                if record.atom_name == "CA"
            ]
            residue_id = residue_records[0].public_residue_id
            if not ca_records:
                raise ValueError(f"residue {residue_id} lacks a CA atom")
            residues.append(
                _choose_alternate(
                    ca_records,
                    residue_id=residue_id,
                    atom_name="CA",
                )
            )
    if not residues:
        raise ValueError("structure contains no protein residues")
    return ProteinSequence(
        sequence="".join(
            _AMINO_ACIDS.get(record.residue_name, "X")
            for record in residues
        ),
        residue_ids=[record.public_residue_id for record in residues],
    )


def validate_backbone_structure(value: object) -> None:
    """Validate the exact canonical backbone-only nominal value."""
    if type(value) is not ProteinStructure:
        raise ValueError("backbone must be a ProteinStructure")
    if value.source != "structure_transform.extract_backbone":
        raise ValueError("backbone producer identity is invalid")
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

    def __init__(self, run_resources: Any, operation: str) -> None:
        self._run_resources = run_resources
        self._operation = operation

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        expected_input = (
            "backbone"
            if self._operation == "backbone_to_structure"
            else "structure"
        )
        if binding_parameters or set(inputs) != {expected_input}:
            raise ValueError(
                "structure transform requires exactly one declared input"
            )
        structure = inputs[expected_input]
        expected_parameters = (
            {"chain_ids"} if self._operation == "select_chains" else set()
        )
        if set(node_parameters) != expected_parameters:
            raise ValueError("structure transform parameters are invalid")
        with self._run_resources.engine_invocation(
            engine_identity=(
                f"structure_transform.{self._operation}.method/2.0.0"
            ),
        ):
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
            if self._operation == "backbone_to_structure":
                if type(structure) is not ProteinStructure:
                    raise ValueError(
                        "backbone bridge requires a ProteinStructure"
                    )
                return {
                    "structure": ProteinStructure(
                        pdb_string=structure.pdb_string,
                        source=(
                            "structure_transform.backbone_to_structure"
                        ),
                    )
                }
        raise ValueError("unknown structure transform operation")
