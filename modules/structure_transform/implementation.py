"""Provider-free, canonical structure conversions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping

from datatypes import (
    Candidate,
    CandidateCollection,
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
    ProteinSequence,
    ProteinStructure,
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


def _parent_atom_line(
    record: _AtomRecord,
    *,
    serial: int,
    residue_name: str,
    residue_number: int,
    atom_name: str,
) -> str:
    line = list(record.line.ljust(80))
    line[0:6] = "ATOM  "
    line[6:11] = f"{serial:5d}"
    line[12:16] = f" {atom_name:<3}"
    line[16] = " "
    line[17:20] = f"{residue_name:>3}"
    line[22:26] = f"{residue_number:4d}"
    line[26] = " "
    return "".join(line).rstrip()


def normalize_csh_parent_span(
    structure: object,
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
            for index, record in enumerate(coordinate_records)
            if record.residue_identity == identity
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

    output_lines: list[str] = []
    normalizations: list[ModifiedResidueNormalization] = []
    emitted: set[tuple[str, str, str]] = set()
    serial = 1
    for record in records:
        if record is None:
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
            source="structure_transform.normalize_csh_parent_span",
        ),
        ModifiedResidueNormalizationCollection(entries=normalizations),
    )


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
        if self._operation == "backbone_to_structure":
            expected_input = "backbone"
        elif self._operation in {
            "extract_sequence_candidates",
            "select_candidate_chains",
        }:
            expected_input = "structure_candidates"
        else:
            expected_input = "structure"
        if binding_parameters or set(inputs) != {expected_input}:
            raise ValueError(
                "structure transform requires exactly one declared input"
            )
        structure = inputs[expected_input]
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
        with self._run_resources.engine_invocation(
            engine_identity=(
                f"structure_transform.{self._operation}.method/2.1.0"
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
            if self._operation == "normalize_csh_parent_span":
                normalized, normalizations = normalize_csh_parent_span(
                    structure
                )
                return {
                    "structure": normalized,
                    "modified_residue_normalizations": normalizations,
                }
            if self._operation == "extract_sequence_candidates":
                children: list[Candidate] = []
                for index, parent in enumerate(
                    _structure_candidate_parents(structure)
                ):
                    children.append(
                        Candidate(
                            candidate_id=f"extracted-sequence-{index}",
                            data=extract_sequence(parent.data),
                            parent_ids=[parent.candidate_id],
                            metadata={
                                "transform": (
                                    "structure_transform."
                                    "extract_sequence_candidates"
                                ),
                                "parent_index": index,
                            },
                        )
                    )
                return {
                    "sequence_candidates": CandidateCollection(
                        collection_id="extracted-sequence-candidates",
                        item_type="protein.sequence",
                        items=children,
                    )
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
                        source=(
                            "structure_transform.backbone_to_structure"
                        ),
                    )
                }
        raise ValueError("unknown structure transform operation")
