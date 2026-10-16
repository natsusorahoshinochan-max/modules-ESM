"""Pure FASTA parsing shared by runtime import and Prompt Studio preview."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

from .errors import ProteinInputError
from datatypes.sequence import ProteinSequence, validate_protein_sequence

_ASCII_UPPER_TRANSLATION = str.maketrans(
    string.ascii_lowercase,
    string.ascii_uppercase,
)


@dataclass(frozen=True, slots=True)
class FastaRecord:
    """One source-addressed record, independent of Candidate identity."""

    header: str
    sequence: str
    line_number: int


def admit_fasta_record(record: FastaRecord, index: int) -> ProteinSequence:
    """Admit one record with the same source-addressed import diagnostic."""
    try:
        return validate_protein_sequence(
            ProteinSequence(record.sequence),
            subject=f"FASTA record {index} at line {record.line_number}",
        )
    except ValueError as error:
        raise ProteinInputError(str(error)) from error


def parse_fasta_entries(payload: bytes) -> tuple[FastaRecord, ...]:
    """Parse ordered records while preserving names and source locations."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProteinInputError("Sequence input must be UTF-8 text") from error

    records: list[FastaRecord] = []
    sequence_parts: list[str] = []
    saw_header = False
    header = ""
    record_line = 1

    def record() -> FastaRecord:
        return FastaRecord(
            header=header,
            sequence="".join(sequence_parts).translate(_ASCII_UPPER_TRANSLATION),
            line_number=record_line,
        )

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if sequence_parts and not saw_header:
                raise ProteinInputError(
                    f"FASTA record 1 at line {line_number} has a misplaced header"
                )
            if saw_header:
                records.append(record())
                sequence_parts = []
            saw_header = True
            header = line[1:].strip()
            record_line = line_number
            continue
        if not saw_header and not sequence_parts:
            record_line = line_number
        sequence_parts.append(re.sub(r"\s+", "", line))

    records.append(record())
    return tuple(records)


def parse_fasta_records(payload: bytes) -> tuple[str, ...]:
    """Return ordered FASTA record sequences without assigning chain IDs."""
    return tuple(record.sequence for record in parse_fasta_entries(payload))


def parse_fasta_sequence(payload: bytes) -> str:
    """Read one record; batch imports own multiple independent records."""
    records = parse_fasta_records(payload)
    if len(records) != 1:
        raise ProteinInputError(
            "Single-sequence import accepts one FASTA record; use batch import "
            "for multiple records"
        )
    return records[0]
