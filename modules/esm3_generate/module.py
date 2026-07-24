"""ESM3 Generate: unified generation producing both sequence and structure candidates."""

import uuid
from pathlib import Path
from typing import Any

from core.module_definition import ModuleDefinition
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinPrompt,
    ScoreCollection,
)


class ESM3GenerateModule(WorkflowModule):
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
        prompt: ProteinPrompt | None = inputs.get("protein_prompt")
        if prompt is None:
            raise ValueError("protein_prompt input is required")

        model_name = str(parameters.get("model_name", "esm3-medium-2024-08"))
        num_steps = int(parameters.get("num_steps", 20))
        temperature = float(parameters.get("temperature", 1.0))
        top_p = float(parameters.get("top_p", 1.0))
        num_samples = int(parameters.get("num_samples", 1))

        has_template_coords = (
            prompt.structure_track is not None
            and any(
                v is not None
                for v in prompt.structure_track.values
                if v is not None
            )
        )
        classification = (
            "prompt_reconstruction" if has_template_coords else "absent"
        )

        from modules.esm3_adapter import (
            create_esm3_client,
            esm_protein_to_sequence,
            esm_protein_to_structure,
            esm_protein_to_scores,
            protein_prompt_to_esm_protein,
        )

        esm_protein = protein_prompt_to_esm_protein(prompt)
        client = create_esm3_client(model_name, context.project_dir)

        from esm.sdk.api import GenerationConfig

        config = GenerationConfig(
            track="sequence",
            num_steps=num_steps,
            temperature=temperature,
            top_p=top_p,
        )

        seq_candidates: list[Candidate] = []
        struct_candidates: list[Candidate] = []
        all_scores_entries = []

        for i in range(num_samples):
            result = client.generate(esm_protein, config)

            # Extract sequence
            seq = esm_protein_to_sequence(result)
            seq_cid = f"seq-{context.run_id}-{i}"
            seq_cand = Candidate(
                candidate_id=seq_cid,
                data=seq,
                parent_ids=[context.node_id],
                metadata={
                    "model": model_name,
                    "sample_index": i,
                    "classification": classification,
                },
            )
            seq_candidates.append(seq_cand)

            # Extract structure (PDB embeds the same sequence)
            struct = esm_protein_to_structure(result)
            struct_cid = f"struct-{context.run_id}-{i}"
            struct_cand = Candidate(
                candidate_id=struct_cid,
                data=struct,
                parent_ids=[context.node_id],
                metadata={
                    "model": model_name,
                    "sample_index": i,
                    "classification": classification,
                },
            )
            struct_candidates.append(struct_cand)

            # Scores reference the sequence candidate
            scores = esm_protein_to_scores(result, seq_cid)
            all_scores_entries.extend(scores.entries)

        return {
            "sequence_candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="protein.sequence",
                items=seq_candidates,
            ),
            "structure_candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="protein.structure",
                items=struct_candidates,
            ),
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=all_scores_entries,
            ),
        }
