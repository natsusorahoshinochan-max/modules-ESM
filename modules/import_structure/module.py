"""Import Structure: reads PDB → ProteinStructure."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure


class ImportStructureModule(WorkflowModule):
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
        pdb_text = Path(file_path).read_text()
        return {"structure": ProteinStructure(pdb_string=pdb_text)}
