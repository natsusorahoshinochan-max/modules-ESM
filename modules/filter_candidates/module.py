"""Filter Candidates: removes candidates that don't satisfy score threshold conditions."""

import json
import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection, ScoreCollection


class FilterCandidatesModule(WorkflowModule):
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

        conditions_raw = parameters.get("conditions", "[]")
        if isinstance(conditions_raw, str):
            conditions = json.loads(conditions_raw)
        else:
            conditions = conditions_raw

        if not conditions:
            return {"candidates": coll}

        # Build map: candidate_id -> {score_id: value}
        score_map: dict[str, dict[str, float]] = {}
        for entry in scores.entries:
            for subj in entry.subjects:
                score_map.setdefault(subj, {})[entry.score_id] = entry.value

        operators = {
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            "==": lambda a, b: abs(a - b) < 1e-9,
            "!=": lambda a, b: abs(a - b) >= 1e-9,
        }

        kept = []
        for item in coll.items:
            cid = item.candidate_id
            cid_scores = score_map.get(cid, {})
            passes = True
            for cond in conditions:
                score_id = cond["score"]
                op = cond["operator"]
                threshold = float(cond["value"])
                if score_id not in cid_scores:
                    passes = False
                    break
                if op not in operators:
                    raise ValueError(f"Unknown operator: {op}")
                if not operators[op](cid_scores[score_id], threshold):
                    passes = False
                    break
            if passes:
                kept.append(item)

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type=coll.item_type,
                items=kept,
            ),
        }
