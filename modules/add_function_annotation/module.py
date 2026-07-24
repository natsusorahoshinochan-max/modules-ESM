"""Add Function Annotation: adds named residue range annotations."""

from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import FunctionAnnotations


class AddFunctionAnnotationModule(WorkflowModule):
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
        existing = inputs.get("existing_annotations")
        if existing is not None:
            fa = FunctionAnnotations(annotations=list(existing.annotations))
        else:
            fa = FunctionAnnotations()

        label = str(parameters.get("label", ""))
        start = int(parameters.get("start", 1))
        end = int(parameters.get("end", 1))

        if label:
            fa.add(label=label, start=start, end=end)

        return {"updated_annotations": fa}
