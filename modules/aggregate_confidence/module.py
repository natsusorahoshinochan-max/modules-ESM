"""Aggregate Confidence: computes summary statistics from confidence scores."""

import statistics
import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import Score, ScoreCollection


class AggregateConfidenceModule(WorkflowModule):
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
        scores: ScoreCollection | None = inputs.get("scores")
        if scores is None:
            raise ValueError("scores input is required")

        # Collect all numeric values
        values = [s.value for s in scores.entries]
        if not values:
            raise ValueError("ScoreCollection has no entries")

        # Collect per-residue values if available
        all_per_residue = []
        for s in scores.entries:
            per_res = s.details.get("per_residue", [])
            if isinstance(per_res, list):
                all_per_residue.extend([v for v in per_res if isinstance(v, (int, float))])

        mean_val = statistics.mean(values)
        median_val = statistics.median(values)
        min_val = min(values)
        max_val = max(values)

        entries = [
            Score(score_id="confidence_mean", value=round(float(mean_val), 4), subjects=[],
                  details={"count": len(values)}),
            Score(score_id="confidence_median", value=round(float(median_val), 4), subjects=[],
                  details={"count": len(values)}),
            Score(score_id="confidence_min", value=round(float(min_val), 4), subjects=[],
                  details={"count": len(values)}),
            Score(score_id="confidence_max", value=round(float(max_val), 4), subjects=[],
                  details={"count": len(values)}),
        ]

        if all_per_residue:
            entries.append(Score(
                score_id="confidence_per_residue_mean",
                value=round(float(statistics.mean(all_per_residue)), 4),
                subjects=[],
                details={"per_residue_count": len(all_per_residue)},
            ))

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=entries,
            ),
        }
