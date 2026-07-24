"""Merge Scores: concatenates multiple ScoreCollections into one."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ScoreCollection


class MergeScoresModule(WorkflowModule):
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
        all_entries = []

        for port_name in ["scores_a", "scores_b", "scores_c"]:
            sc = inputs.get(port_name)
            if sc is not None:
                if not isinstance(sc, ScoreCollection):
                    raise ValueError(
                        f"Input {port_name} is not a ScoreCollection"
                    )
                all_entries.extend(sc.entries)

        if not all_entries:
            raise ValueError("At least one score input is required")

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=all_entries,
            ),
        }
