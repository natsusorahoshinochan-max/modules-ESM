"""Build Residue Layout: creates a target residue layout."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ResidueLayout


class BuildResidueLayoutModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        chain_id = str(parameters.get("chain_id", "A"))
        length = int(parameters.get("length", 1))
        layout = ResidueLayout(chain_id=chain_id, length=length)
        return {"layout": layout}
