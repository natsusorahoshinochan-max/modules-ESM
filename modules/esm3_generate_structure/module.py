"""ESM3 Generate Structure: generates protein structures from a ProteinPrompt."""

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
)
# adapter functions are imported inside run() for testability


class ESM3GenerateStructureModule(WorkflowModule):
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

        # Determine output classification
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
            esm_protein_to_scores,
            esm_protein_to_structure,
            protein_prompt_to_esm_protein,
        )

        # Build ESMProtein
        esm_protein = protein_prompt_to_esm_protein(prompt)

        # Create client
        client = create_esm3_client(model_name, context.project_dir)

        # Generate
        from esm.sdk.api import GenerationConfig

        config = GenerationConfig(
            track="structure",
            num_steps=num_steps,
            temperature=temperature,
            top_p=top_p,
        )

        candidates: list[Candidate] = []
        all_scores_entries = []

        for i in range(num_samples):
            result = client.generate(esm_protein, config)
            structure = esm_protein_to_structure(result)
            cid = f"struct-{context.run_id}-{i}"
            cand = Candidate(
                candidate_id=cid,
                data=structure,
                parent_ids=[context.node_id],
                metadata={
                    "model": model_name,
                    "sample_index": i,
                    "classification": classification,
                },
            )
            candidates.append(cand)

            scores = esm_protein_to_scores(result, cid)
            all_scores_entries.extend(scores.entries)

        from datatypes import ScoreCollection
        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="protein.structure",
                items=candidates,
            ),
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=all_scores_entries,
            ),
        }
