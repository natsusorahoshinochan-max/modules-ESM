"""Structure Alignment: sequence-aware superposition of two protein structures."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure
from modules.structure_alignment import align_structures


class StructureAlignModule(WorkflowModule):
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
        ref_struct: ProteinStructure | None = inputs.get("reference")
        mob_struct: ProteinStructure | None = inputs.get("mobile")

        if ref_struct is None:
            raise ValueError("reference input is required")
        if mob_struct is None:
            raise ValueError("mobile input is required")

        return {"alignment": align_structures(ref_struct, mob_struct)}
