"""Sort Candidates: sorts candidates by a score value."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection, ScoreCollection


class SortCandidatesModule(WorkflowModule):
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
        scores: ScoreCollection | None = inputs.get("scores")

        if coll is None:
            raise ValueError("candidates input is required")
        if scores is None:
            raise ValueError("scores input is required")

        score_id = str(parameters.get("score", "plddt"))
        order = str(parameters.get("order", "descending"))

        # Build score lookup
        cid_scores: dict[str, float] = {}
        for entry in scores.entries:
            if entry.score_id == score_id:
                for subj in entry.subjects:
                    cid_scores[subj] = entry.value

        reverse = order == "descending"
        sorted_items = sorted(
            coll.items,
            key=lambda item: cid_scores.get(item.candidate_id, float("-inf") if not reverse else float("inf")),
            reverse=reverse,
        )

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type=coll.item_type,
                items=sorted_items,
            ),
        }
