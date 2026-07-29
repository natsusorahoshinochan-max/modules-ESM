"""Legacy agreement module backed by the cohesive annotation package."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from modules.structure_annotation.legacy import (
    secondary_structure_agreement_legacy,
)


class SecondaryStructureAgreementModule(WorkflowModule):
    def __init__(self) -> None:
        self._definition = ModuleDefinition.from_yaml(
            Path(__file__).parent / "definition.yaml"
        )

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        del context
        return secondary_structure_agreement_legacy(inputs, parameters)
