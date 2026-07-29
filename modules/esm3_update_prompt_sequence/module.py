"""Update Prompt Sequence: replaces sequence track, preserves all other tracks."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from modules.prompt_authoring.domain import replace_prompt_sequence


class UpdatePromptSequenceModule(WorkflowModule):
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
        updated = replace_prompt_sequence(
            inputs.get("protein_prompt"),
            inputs.get("sequence"),
        )
        return {"protein_prompt": updated}
