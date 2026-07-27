"""Import Sequence: reads FASTA → ProteinSequence."""

import re
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinSequence


class ImportSequenceModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(self, inputs: dict[str, Any], parameters: dict[str, Any],
            context: RunContext) -> dict[str, Any]:
        file_path = parameters.get("file_path", "")
        if not file_path:
            raise ValueError("file_path parameter is required")
        text = context.input_path(file_path).read_text()
        # Parse FASTA: strip header line(s) starting with >
        lines = text.strip().split("\n")
        seq_lines = [l.strip() for l in lines if not l.startswith(">") and l.strip()]
        sequence = "".join(seq_lines)
        # Remove whitespace within sequence
        sequence = re.sub(r"\s+", "", sequence)
        return {"sequence": ProteinSequence(sequence=sequence)}
