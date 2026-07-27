"""ESM3 Generate Sequence: generates protein sequences from a ProteinPrompt."""

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


class ESM3GenerateSequenceModule(WorkflowModule):
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
            esm_protein_to_sequence,
            protein_prompt_to_esm_protein,
            validate_esm3_structure_response,
        )

        # Build ESMProtein
        esm_protein = protein_prompt_to_esm_protein(prompt)
        source_classification = (
            "prompt_reconstruction" if esm_protein.coordinates is not None else "absent"
        )

        # Create client
        client = create_esm3_client(model_name, context.project_dir)

        # Generate
        from esm.sdk.api import GenerationConfig

        config = GenerationConfig(
            track="sequence",
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
                "generate(track=sequence)",
                context=context,
                model_name=model_name,
            )
            seq = esm_protein_to_sequence(result, prompt.num_residues)
            cid = f"seq-{context.run_id}-{i}"
            if source_classification == "prompt_reconstruction":
                validate_esm3_structure_response(
                    result,
                    expected_sequence=seq.sequence,
                    expected_length=prompt.num_residues,
                )
            scores = esm_protein_to_scores(
                result,
                cid,
                require_structure_metrics=(
                    source_classification == "prompt_reconstruction"
                ),
            )
            cand = Candidate(
                candidate_id=cid,
                data=seq,
                parent_ids=[context.node_id],
                metadata=esm3_candidate_metadata(
                    model_name=model_name,
                    operation="generate(track=sequence)",
                    sample_index=i,
                    classification=source_classification,
                ),
            )
            candidates.append(cand)

            all_scores_entries.extend(scores.entries)

        from datatypes import ScoreCollection

        return {
            "candidates": CandidateCollection(
                collection_id=str(uuid.uuid4()),
                item_type="protein.sequence",
                items=candidates,
            ),
            "scores": ScoreCollection(
                collection_id=str(uuid.uuid4()),
                entries=all_scores_entries,
            ),
        }
