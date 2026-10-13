"""Read-only scientific input summaries for the Project Input picker."""

from __future__ import annotations

from typing import Literal, TypedDict

from datatypes.structure import ProteinStructure, validate_protein_structure

from .errors import ProteinInputError
from .fasta import admit_fasta_record, parse_fasta_entries


class FastaRecordInspection(TypedDict):
    record_index: int
    header: str
    display_name: str
    line_number: int
    length: int


class FastaInspection(TypedDict):
    format: Literal["fasta"]
    records: list[FastaRecordInspection]
    total_length: int


class PdbInspection(TypedDict):
    format: Literal["pdb"]
    chain_ids: list[str]


def read_structure_input(payload: bytes) -> ProteinStructure:
    """Read PDB text using the same newline normalization as runtime import."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProteinInputError("Structure input must be UTF-8 text") from error
    canonical = text.replace("\r\n", "\n").replace("\r", "\n")
    return ProteinStructure(pdb_string=canonical.rstrip("\n") + "\n")


def inspect_project_input(
    payload: bytes,
    format: Literal["fasta", "pdb"],
) -> FastaInspection | PdbInspection:
    """Inspect the explicitly selected format without publishing scientific data."""
    if format == "fasta":
        records: list[FastaRecordInspection] = []
        for index, record in enumerate(parse_fasta_entries(payload), start=1):
            sequence = admit_fasta_record(record, index)
            records.append({
                "record_index": index,
                "header": record.header,
                "display_name": record.header or f"Record {index}",
                "line_number": record.line_number,
                "length": len(sequence.sequence),
            })
        return {
            "format": "fasta",
            "records": records,
            "total_length": sum(record["length"] for record in records),
        }
    structure = read_structure_input(payload)
    try:
        validate_protein_structure(structure)
    except ValueError as error:
        raise ProteinInputError(str(error)) from error
    return {
        "format": "pdb",
        "chain_ids": list(dict.fromkeys(
            line[21]
            for line in structure.pdb_string.splitlines()
            if line.startswith(("ATOM  ", "HETATM"))
        )),
    }
