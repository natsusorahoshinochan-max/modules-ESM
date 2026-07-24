"""Top-K: keeps the first K candidates from a collection."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection


class TopKModule(WorkflowModule):
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
        coll: CandidateCollection | None = inputs.get("candidates")
        if coll is None:
            raise ValueError("candidates input is required")

        k = int(parameters.get("k", 10))
        if k < 1:
            raise ValueError("k must be at least 1")

        kept = coll.items[:k]

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type=coll.item_type,
                items=kept,
            ),
        }
