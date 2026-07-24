"""Concatenate Candidates: merges multiple CandidateCollections into one."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection


class ConcatCandidatesModule(WorkflowModule):
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
        all_items = []
        item_type: str | None = None

        for port_name in ["candidates_a", "candidates_b", "candidates_c"]:
            coll = inputs.get(port_name)
            if coll is not None:
                if not isinstance(coll, CandidateCollection):
                    raise ValueError(
                        f"Input {port_name} is not a CandidateCollection"
                    )
                if item_type is None:
                    item_type = coll.item_type
                elif coll.item_type != item_type:
                    raise ValueError(
                        f"All collections must have the same item_type: "
                        f"got {item_type} and {coll.item_type}"
                    )
                all_items.extend(coll.items)

        if not all_items:
            raise ValueError("At least one candidate input is required")

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type=item_type,
                items=all_items,
            ),
        }
