"""ProteinMPNN Score: scores a sequence against a structure."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinSequence, ProteinStructure, Score, ScoreCollection
from modules.proteinmpnn.adapter import score_sequence


class ProteinMPNNScoreModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition_score.yaml"
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
        structure: ProteinStructure | None = inputs.get("structure")
        sequence: ProteinSequence | None = inputs.get("sequence")
        if structure is None:
            raise ValueError("structure input is required")
        if sequence is None:
            raise ValueError("sequence input is required")

        model_name = str(parameters.get("model_name", "v_48_020"))

        score_val = score_sequence(
            pdb_string=structure.pdb_string,
            sequence=sequence.sequence,
            model_name=model_name,
            temp_dir=context.temp_dir,
        )

        return {
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=[
                    Score(
                        score_id="proteinmpnn_score",
                        value=score_val,
                        subjects=[context.node_id],
                    )
                ],
            ),
        }
