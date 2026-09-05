"""Pure FASTA parsing shared by runtime import and Prompt Studio preview."""

from __future__ import annotations

import re
import string


_ASCII_UPPER_TRANSLATION = str.maketrans(
    string.ascii_lowercase,
    string.ascii_uppercase,
)


def parse_fasta_records(payload: bytes) -> tuple[str, ...]:
    """Return ordered FASTA record sequences without assigning chain IDs."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Sequence input must be UTF-8 text") from error

    records: list[str] = []
    sequence_parts: list[str] = []
    saw_header = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if sequence_parts and not saw_header:
                raise ValueError("Sequence input has a misplaced FASTA header")
            if saw_header:
                records.append("".join(sequence_parts))
                sequence_parts = []
            saw_header = True
            continue
        sequence_parts.append(re.sub(r"\s+", "", line))

    if saw_header or sequence_parts:
        records.append("".join(sequence_parts))
    else:
        records.append("")
    return tuple(
        sequence.translate(_ASCII_UPPER_TRANSLATION) for sequence in records
    )


def parse_fasta_sequence(payload: bytes) -> str:
    """Return the runtime ProteinSequence payload across ordered records."""
    return "".join(parse_fasta_records(payload))
