"""Export Sequence: writes ProteinSequence → FASTA file."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.recovery import MAX_PUBLIC_ARTIFACT_BYTES
from core.run_context import RunContext
from core.storage import (
    validate_relative_path,
    write_private_new_file,
)
from core.workflow_module import WorkflowModule
from datatypes import ProteinSequence


class ExportSequenceModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(self, inputs: dict[str, Any], parameters: dict[str, Any],
            context: RunContext) -> dict[str, Any]:
        sequence: ProteinSequence = inputs.get("sequence")
        if sequence is None:
            raise ValueError("Missing input: sequence")
        filename = parameters.get("filename", "exported.fasta")
        filename_parts = validate_relative_path(
            filename,
            "artifact_name",
            allow_nested=False,
        )
        # Write FASTA format with 60-char lines
        header = f">exported_sequence len={len(sequence)}"
        chars = sequence.sequence
        if not chars.isascii():
            raise ValueError(
                "Sequence export requires ASCII amino-acid symbols"
            )
        sequence_line_count = (len(chars) + 59) // 60
        serialized_size = (
            len(header.encode())
            + 1
            + len(chars)
            + sequence_line_count
        )
        if serialized_size > MAX_PUBLIC_ARTIFACT_BYTES:
            raise ValueError(
                "FASTA artifact exceeds the public retrieval limit"
            )
        lines = [header]
        for i in range(0, len(chars), 60):
            lines.append(chars[i:i + 60])
        payload = ("\n".join(lines) + "\n").encode()
        out_path = write_private_new_file(
            context.output_dir or "",
            filename_parts,
            payload,
            field="artifact_name",
        )
        return {"file_path": str(out_path)}
