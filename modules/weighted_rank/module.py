"""Weighted Rank: ranks candidates by weighted combination of scores."""

import json
import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection, Score, ScoreCollection


class WeightedRankModule(WorkflowModule):
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

        metrics_raw = parameters.get("metrics", "[]")
        if isinstance(metrics_raw, str):
            metrics = json.loads(metrics_raw)
        else:
            metrics = metrics_raw

        if not metrics:
            raise ValueError("At least one metric is required for weighted ranking")

        # Build score lookup per candidate
        cid_scores: dict[str, dict[str, float]] = {}
        for entry in scores.entries:
            for subj in entry.subjects:
                cid_scores.setdefault(subj, {})[entry.score_id] = entry.value

        # Compute weighted sum for each candidate
        weighted: list[tuple[float, str]] = []
        for item in coll.items:
            cid = item.candidate_id
            cs = cid_scores.get(cid, {})
            total = 0.0
            for m in metrics:
                sid = m["score"]
                w = float(m["weight"])
                val = cs.get(sid, 0.0)
                total += w * val
            weighted.append((total, cid))

        # Sort descending by weighted sum
        weighted.sort(key=lambda x: x[0], reverse=True)

        # Reorder items
        cid_order = {cid: i for i, (_, cid) in enumerate(weighted)}
        sorted_items = sorted(coll.items, key=lambda item: cid_order.get(item.candidate_id, len(coll.items)))

        # Add weighted rank scores
        rank_entries = []
        for total, cid in weighted:
            rank_entries.append(Score(
                score_id="weighted_rank",
                value=round(float(total), 4),
                subjects=[cid],
                details={"metrics": metrics},
            ))

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type=coll.item_type,
                items=sorted_items,
            ),
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=rank_entries,
            ),
        }
