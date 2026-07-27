"""ESMFold2 Fold: folds protein sequences into 3D structures."""

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
    ProteinStructure,
    ScoreCollection,
)
# adapter functions are imported inside run() for testability


class ESMFold2FoldModule(WorkflowModule):
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

        model_name = str(parameters.get("model_name", "esmfold2-fast-2026-05"))
        include_pae = bool(parameters.get("include_pae", False))
        include_embeddings = bool(parameters.get("include_embeddings", False))

        from modules.esmfold2_adapter import fold_sequence

        candidates: list[Candidate] = []
        all_scores_entries = []

        for parent_id, seq in sequences:
            context.record_provider_call(
                "biohub",
                "fold",
                model=model_name,
            )
            structure, scores = fold_sequence(
                sequence=seq,
                model_name=model_name,
                include_pae=include_pae,
                include_embeddings=include_embeddings,
                project_dir=context.project_dir,
            )

            cid = f"fold-{context.run_id}-{parent_id}"
            cand = Candidate(
                candidate_id=cid,
                data=structure,
                parent_ids=[parent_id],
                metadata={
                    "model": model_name,
                    "backend": "esmfold2",
                    "include_pae": include_pae,
                    "include_embeddings": include_embeddings,
                },
            )
            candidates.append(cand)

            # Update score subjects to reference the new candidate
            for entry in scores.entries:
                entry.subjects = [cid]
            all_scores_entries.extend(scores.entries)

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
