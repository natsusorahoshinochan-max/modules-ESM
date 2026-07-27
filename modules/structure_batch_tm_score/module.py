"""Batch TM-score from shared sequence-aware StructureAlignment evidence."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import (
    CandidateCollection,
    ScoreCollection,
    StructureAlignment,
)
from modules.structure_tm_score.scoring import (
    score_reference_normalized_alignment,
)


class BatchTMScoreModule(WorkflowModule):
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
        score_id: str = parameters.get("score_id", "tm_score")
        alignments: CandidateCollection | None = inputs.get("alignments")

        if alignments is None:
            raise ValueError("alignments input is required")
        if len(alignments) == 0:
            raise ValueError("alignments collection is empty")
        if alignments.item_type != "structure.alignment":
            raise ValueError(
                f"alignments item_type must be structure.alignment, "
                f"got {alignments.item_type}"
            )

        entries = []
        for cand in alignments.items:
            alignment = cand.data
            if not isinstance(alignment, StructureAlignment):
                raise ValueError(
                    f"Alignment candidate {cand.candidate_id} data "
                    f"is not a StructureAlignment"
                )

            entries.append(
                score_reference_normalized_alignment(
                    alignment,
                    score_id=score_id,
                    subjects=[cand.candidate_id],
                )
            )

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=entries,
            ),
        }
