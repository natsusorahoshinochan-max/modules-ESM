"""Export Sequence: writes ProteinSequence → FASTA file."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
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
        out_path = context.output_path(filename)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Write FASTA format with 60-char lines
        header = f">exported_sequence len={len(sequence)}"
        chars = sequence.sequence
        lines = [header]
        for i in range(0, len(chars), 60):
            lines.append(chars[i:i + 60])
        out_path.write_text("\n".join(lines) + "\n")
        return {"file_path": str(out_path)}
