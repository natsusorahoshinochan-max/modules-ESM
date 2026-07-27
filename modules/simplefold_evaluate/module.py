"""SimpleFold Evaluate: scores existing structures without re-folding."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import (
    CandidateCollection,
    ProteinStructure,
    ScoreCollection,
)
# adapter functions are imported inside run() for testability


class SimpleFoldEvaluateModule(WorkflowModule):
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
        # Collect structures to evaluate
        structures: list[tuple[str, ProteinStructure]] = []

        single_struct: ProteinStructure | None = inputs.get("structure")
        coll: CandidateCollection | None = inputs.get("candidates")

        if single_struct is not None:
            structures.append(("struct-0", single_struct))
        elif coll is not None:
            if coll.item_type != "protein.structure":
                raise ValueError(
                    f"Expected candidate.collection of protein.structure, "
                    f"got {coll.item_type}"
                )
            for item in coll.items:
                if isinstance(item.data, ProteinStructure):
                    structures.append((item.candidate_id, item.data))
                else:
                    raise ValueError(
                        f"Candidate {item.candidate_id} data is not a ProteinStructure"
                    )
        else:
            raise ValueError(
                "Either 'structure' or 'candidates' input is required"
            )

        if not structures:
            raise ValueError("No structures to evaluate")

        model_name = str(parameters.get("model_name", "simplefold_360M"))

        from modules.simplefold_adapter import evaluate_structure

        all_scores_entries = []

        for parent_id, struct in structures:
            scores = evaluate_structure(
                structure=struct,
                model_name=model_name,
                project_dir=context.temp_dir,
            )

            # Update score subjects to reference the parent candidate
            for entry in scores.entries:
                entry.subjects = [parent_id]
            all_scores_entries.extend(scores.entries)

        from datatypes import ScoreCollection as SC
        return {
            "scores": SC(
                collection_id=str(uuid.uuid4()),
                entries=all_scores_entries,
            ),
        }
