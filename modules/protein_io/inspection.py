"""Read-only scientific input summaries for the Project Input picker."""

from __future__ import annotations

from typing import Literal, TypedDict

from datatypes.structure_format import read_mmcif_atoms

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
    format: Literal["pdb", "mmcif"]
    chain_ids: list[str]


def read_structure_input(payload: bytes) -> ProteinStructure:
    """Read PDB or mmCIF without changing authored identities or coordinates."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProteinInputError("Structure input must be UTF-8 text") from error
    canonical = text.replace("\r\n", "\n").replace("\r", "\n")
    first_record = next((line.strip() for line in canonical.splitlines()
                         if line.strip() and not line.lstrip().startswith("#")), "")
    format: Literal["pdb", "mmcif"] = "mmcif" if first_record.lower().startswith("data_") else "pdb"
    return ProteinStructure(text=canonical.rstrip("\n") + "\n", format=format)



def inspect_project_input(
    payload: bytes,
    format: Literal["fasta", "pdb", "mmcif", "structure"],
) -> FastaInspection | PdbInspection:
    """Inspect the selected input class or format without publishing data."""
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
    if format != "structure" and structure.format != format:
        raise ProteinInputError(f"Selected {format} format does not match the structure input")
    try:
        validate_protein_structure(structure)
    except ValueError as error:
        raise ProteinInputError(str(error)) from error
    return {
        "format": structure.format,
        "chain_ids": list(dict.fromkeys(
            atom.chain_id for atom in read_mmcif_atoms(structure.text)
        )) if structure.format == "mmcif" else list(dict.fromkeys(
            line[21] for line in structure.text.splitlines()
            if line.startswith(("ATOM  ", "HETATM"))
        )),
    }
