"""Diversity Select: picks K candidates with diverse score values."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection, ScoreCollection


class DiversitySelectModule(WorkflowModule):
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

        k = int(parameters.get("k", 10))
        div_score_id = str(parameters.get("diversity_score", "plddt"))

        # Build score lookup
        cid_score: dict[str, float] = {}
        for entry in scores.entries:
            if entry.score_id == div_score_id:
                for subj in entry.subjects:
                    cid_score[subj] = entry.value

        if len(coll.items) <= k:
            return {"candidates": coll}

        # Greedy diversity selection: pick extremes first, then fill gaps
        # Sort candidates by score
        scored_items = sorted(
            [(cid_score.get(item.candidate_id, 0.0), item) for item in coll.items],
            key=lambda x: x[0],
        )

        if not scored_items or k < 1:
            return {"candidates": coll}

        # Take evenly spaced candidates across the sorted range
        n = len(scored_items)
        if k == 1:
            # Take median
            selected = [scored_items[n // 2][1]]
        else:
            indices = [int(i * (n - 1) / (k - 1)) for i in range(k)]
            selected = [scored_items[idx][1] for idx in indices]

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type=coll.item_type,
                items=selected,
            ),
        }
