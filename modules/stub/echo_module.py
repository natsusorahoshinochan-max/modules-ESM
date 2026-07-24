"""Echo module: returns input text unchanged, with optional repeat."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule


class EchoModule(WorkflowModule):
    """Stub Echo module for testing the execution engine.

    Takes a text input, repeats it N times, and outputs the concatenated result.
    """

    def __init__(self) -> None:
        definition_path = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(definition_path)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        text = inputs.get("text", "")
        repeat = int(parameters.get("repeat", 1))
        prefix = str(parameters.get("prefix", ""))

        result = ""
        for i in range(repeat):
            if i > 0:
                result += "\n"
            result += f"{prefix}{text}"

        return {"text": result}
