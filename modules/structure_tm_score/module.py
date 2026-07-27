"""TM-score: computes standard reference-normalized TM-score."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ScoreCollection, StructureAlignment
from modules.structure_tm_score.scoring import (
    score_reference_normalized_alignment,
)


class StructureTMScoreModule(WorkflowModule):
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
        alignment: StructureAlignment | None = inputs.get("alignment")
        if alignment is None:
            raise ValueError("alignment input is required")
        candidate_id = str(parameters.get("candidate_id", "")).strip()
        if not candidate_id:
            raise ValueError("candidate_id is required for structure TM-score")
        score_id = str(parameters.get("score_id", "tm_score"))

        entries = [
            score_reference_normalized_alignment(
                alignment,
                score_id=score_id,
                subjects=[candidate_id],
            )
        ]

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=entries,
            ),
        }
