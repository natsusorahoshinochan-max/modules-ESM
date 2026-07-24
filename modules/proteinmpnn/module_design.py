"""ProteinMPNN Design: generates sequence candidates from a structure."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)
from modules.proteinmpnn.adapter import design_sequences


class ProteinMPNNDesignModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition_design.yaml"
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
        if structure is None:
            raise ValueError("structure input is required")
        # Accept CandidateCollection (first item) for DAG compatibility
        if isinstance(structure, CandidateCollection):
            if len(structure) == 0:
                raise ValueError("structure CandidateCollection is empty")
            structure = structure.items[0].data
            if not isinstance(structure, ProteinStructure):
                raise ValueError(
                    "First candidate in structure collection is not a ProteinStructure")


        constraints: ProteinMPNNConstraints | None = inputs.get("constraints")

        model_name = str(parameters.get("model_name", "v_48_020"))
        num_sequences = int(parameters.get("num_sequences", 1))
        temperature = float(parameters.get("temperature", 0.1))

        sequences, native_score = design_sequences(
            pdb_string=structure.pdb_string,
            model_name=model_name,
            num_sequences=num_sequences,
            temperature=temperature,
            constraints=constraints,
        )

        candidates: list[Candidate] = []
        all_scores: list[Score] = []

        for i, seq in enumerate(sequences):
            cid = f"mpnn-{context.run_id}-{i}"
            cand = Candidate(
                candidate_id=cid,
                data=seq,
                parent_ids=[context.node_id],
                metadata={
                    "model": model_name,
                    "sample_index": i,
                    "temperature": temperature,
                },
            )
            candidates.append(cand)

        if native_score is not None:
            all_scores.append(Score(
                score_id="proteinmpnn_score",
                value=native_score,
                subjects=[c.candidate_id for c in candidates],
            ))

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="protein.sequence",
                items=candidates,
            ),
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=all_scores,
            ),
        }
