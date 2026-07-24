"""SimpleFold Fold: folds protein sequences using lightweight 100M model."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ScoreCollection,
)
# adapter functions are imported inside run() for testability


class SimpleFoldFoldModule(WorkflowModule):
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
        # Collect sequences to fold
        sequences: list[tuple[str, ProteinSequence]] = []

        single_seq: ProteinSequence | None = inputs.get("sequence")
        coll: CandidateCollection | None = inputs.get("candidates")

        if single_seq is not None:
            sequences.append(("seq-0", single_seq))
        elif coll is not None:
            if coll.item_type != "protein.sequence":
                raise ValueError(
                    f"Expected candidate.collection of protein.sequence, "
                    f"got {coll.item_type}"
                )
            for item in coll.items:
                if isinstance(item.data, ProteinSequence):
                    sequences.append((item.candidate_id, item.data))
                else:
                    raise ValueError(
                        f"Candidate {item.candidate_id} data is not a ProteinSequence"
                    )
        else:
            raise ValueError(
                "Either 'sequence' or 'candidates' input is required"
            )

        if not sequences:
            raise ValueError("No sequences to fold")

        model_name = str(parameters.get("model_name", "simplefold_100M"))
        num_steps = int(parameters.get("num_steps", 50))
        num_samples = int(parameters.get("num_samples", 1))

        from modules.simplefold_adapter import fold_sequence

        candidates: list[Candidate] = []
        all_scores_entries = []

        for parent_id, seq in sequences:
            structures, scores = fold_sequence(
                sequence=seq,
                model_name=model_name,
                num_steps=num_steps,
                num_samples=num_samples,
                project_dir=context.project_dir,
            )

            for sample_idx, struct in enumerate(structures):
                cid = f"sfold-{context.run_id}-{parent_id}-{sample_idx}"
                cand = Candidate(
                    candidate_id=cid,
                    data=struct,
                    parent_ids=[parent_id],
                    metadata={
                        "model": model_name,
                        "backend": "simplefold",
                        "num_steps": num_steps,
                        "sample_index": sample_idx,
                    },
                )
                candidates.append(cand)

                # Update score subjects to reference the new candidate
                for entry in scores.entries:
                    if entry.details.get("sample_index") == sample_idx:
                        entry.subjects = [cid]
                        all_scores_entries.append(entry)

        from datatypes import ScoreCollection as SC
        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="protein.structure",
                items=candidates,
            ),
            "scores": SC(
                collection_id=str(uuid.uuid4()),
                entries=all_scores_entries,
            ),
        }
