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
        candidate_ids: set[str] = set()
        for item in coll.items:
            if item.candidate_id in candidate_ids:
                raise ValueError(
                    f"Duplicate Candidate ID {item.candidate_id!r}"
                )
            candidate_ids.add(item.candidate_id)
        required_score_ids: set[str] = set()
        for metric in metrics:
            score_id = metric["score"]
            if score_id in required_score_ids:
                raise ValueError(f"Duplicate metric score ID {score_id!r}")
            required_score_ids.add(score_id)
        scores_by_candidate: dict[str, dict[str, float]] = {}
        for entry in scores.entries:
            if entry.score_id in required_score_ids and not entry.subjects:
                raise ValueError(
                    f"Required score {entry.score_id!r} has no Candidate subjects"
                )
            for subject_candidate_id in entry.subjects:
                if (
                    entry.score_id in required_score_ids
                    and subject_candidate_id not in candidate_ids
                ):
                    raise ValueError(
                        f"Score subject {subject_candidate_id!r} is not present "
                        "in candidates"
                    )
                if (
                    entry.score_id in required_score_ids
                    and entry.score_id
                    in scores_by_candidate.get(subject_candidate_id, {})
                ):
                    raise ValueError(
                        f"Duplicate Candidate {subject_candidate_id!r} score "
                        f"{entry.score_id!r}"
                    )
                scores_by_candidate.setdefault(
                    subject_candidate_id,
                    {},
                )[entry.score_id] = entry.value

        # Compute weighted sum for each candidate
        weighted_totals: list[tuple[float, str]] = []
        for item in coll.items:
            candidate_id = item.candidate_id
            candidate_scores = scores_by_candidate.get(candidate_id, {})
            total = 0.0
            for metric in metrics:
                required_score_id = metric["score"]
                weight = float(metric["weight"])
                if required_score_id not in candidate_scores:
                    raise ValueError(
                        f"Required score {required_score_id!r} is missing for "
                        f"Candidate {candidate_id!r}"
                    )
                score_value = candidate_scores[required_score_id]
                total += weight * score_value
            weighted_totals.append((total, candidate_id))

        # Sort descending by weighted sum, then by Candidate ID for stable ties.
        weighted_totals.sort(key=lambda item: (-item[0], item[1]))

        # Reorder items
        rank_by_candidate_id = {
            candidate_id: rank
            for rank, (_, candidate_id) in enumerate(weighted_totals)
        }
        sorted_items = sorted(
            coll.items,
            key=lambda item: rank_by_candidate_id[item.candidate_id],
        )

        # Add weighted rank scores
        weighted_rank_entries = []
        for total, candidate_id in weighted_totals:
            weighted_rank_entries.append(
                Score(
                    score_id="weighted_rank",
                    value=float(total),
                    subjects=[candidate_id],
                    details={"metrics": metrics},
                )
            )

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type=coll.item_type,
                items=sorted_items,
            ),
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=[*scores.entries, *weighted_rank_entries],
            ),
        }
