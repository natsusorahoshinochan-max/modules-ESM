"""Pareto Select: returns non-dominated candidates across multiple scores."""

import json
import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import CandidateCollection, ScoreCollection


class ParetoSelectModule(WorkflowModule):
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

        raw_list = parameters.get("scores_list", "[]")
        if isinstance(raw_list, str):
            score_ids = json.loads(raw_list)
        else:
            score_ids = raw_list

        if not score_ids:
            raise ValueError("At least one score_id is required for Pareto selection")

        # Build score vectors per candidate
        cid_scores: dict[str, dict[str, float]] = {}
        for entry in scores.entries:
            if entry.score_id in score_ids:
                for subj in entry.subjects:
                    cid_scores.setdefault(subj, {})[entry.score_id] = entry.value

        # Build vectors for candidates that have all required scores
        vecs: dict[str, tuple[float, ...]] = {}
        for item in coll.items:
            cid = item.candidate_id
            cs = cid_scores.get(cid, {})
            if all(sid in cs for sid in score_ids):
                vecs[cid] = tuple(cs[sid] for sid in score_ids)

        if not vecs:
            return {
                "candidates": CandidateCollection(
                    collection_id=str(uuid.uuid4()),
                    item_type=coll.item_type,
                    items=[],
                ),
            }

        # Pareto filter: candidate A dominates B if A >= B on all dimensions
        # and A > B on at least one (all scores maximized).
        cids = list(vecs.keys())
        dominated: set[str] = set()

        for i in range(len(cids)):
            if cids[i] in dominated:
                continue
            for j in range(len(cids)):
                if i == j or cids[j] in dominated:
                    continue
                vi = vecs[cids[i]]
                vj = vecs[cids[j]]
                if all(vi[k] >= vj[k] for k in range(len(score_ids))) and any(
                    vi[k] > vj[k] for k in range(len(score_ids))
                ):
                    dominated.add(cids[j])

        pareto_items = [item for item in coll.items if item.candidate_id in vecs and item.candidate_id not in dominated]

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type=coll.item_type,
                items=pareto_items,
            ),
        }
