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

        from modules.esm3_adapter import (
            call_esm3_provider,
            create_esm3_client,
            esm3_candidate_metadata,
            esm_protein_to_scores,
            esm_protein_to_structure,
            protein_prompt_to_esm_protein,
        )

        # Build ESMProtein
        esm_protein = protein_prompt_to_esm_protein(prompt)
        classification = (
            "prompt_reconstruction"
            if esm_protein.coordinates is not None
            else "sampled_structure"
        )

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
            result = call_esm3_provider(
                client,
                esm_protein,
                config,
                "generate(track=structure)",
                model_name=model_name,
            )
            structure = esm_protein_to_structure(
                result,
                expected_length=prompt.num_residues,
            )
            cid = f"struct-{context.run_id}-{i}"
            cand = Candidate(
                candidate_id=cid,
                data=structure,
                parent_ids=[context.node_id],
                metadata=esm3_candidate_metadata(
                    model_name=model_name,
                    operation="generate(track=structure)",
                    sample_index=i,
                    classification=classification,
                ),
            )
            candidates.append(cand)

            scores = esm_protein_to_scores(
                result,
                cid,
                require_structure_metrics=True,
            )
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
