"""Export Structure: writes ProteinStructure → PDB file."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure


class ExportStructureModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(self, inputs: dict[str, Any], parameters: dict[str, Any],
            context: RunContext) -> dict[str, Any]:
        structure: ProteinStructure = inputs.get("structure")
        if structure is None:
            raise ValueError("Missing input: structure")
        filename = parameters.get("filename", "exported.pdb")
        out_path = context.output_path(filename)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(structure.pdb_string)
        return {"file_path": str(out_path)}
