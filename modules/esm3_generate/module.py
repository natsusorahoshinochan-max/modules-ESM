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

        from modules.esm3_adapter import (
            call_esm3_provider,
            create_esm3_client,
            esm3_candidate_metadata,
            esm_protein_to_scores,
            esm_protein_to_sequence,
            esm_protein_to_structure,
            protein_prompt_to_esm_protein,
            structure_sampling_input,
            validate_esm3_structure_response,
        )

        esm_protein = protein_prompt_to_esm_protein(prompt)
        sequence_source_classification = (
            "prompt_reconstruction" if esm_protein.coordinates is not None else "absent"
        )
        client = create_esm3_client(model_name, context.project_dir)

        from esm.sdk.api import GenerationConfig

        sequence_config = GenerationConfig(
            track="sequence",
            num_steps=num_steps,
            temperature=temperature,
            top_p=top_p,
        )
        structure_config = GenerationConfig(
            track="structure",
            num_steps=num_steps,
            temperature=temperature,
            top_p=top_p,
        )

        seq_candidates: list[Candidate] = []
        struct_candidates: list[Candidate] = []
        all_scores_entries = []

        for i in range(num_samples):
            sequence_result = call_esm3_provider(
                client,
                esm_protein,
                sequence_config,
                "generate(track=sequence)",
                context=context,
                model_name=model_name,
            )

            # Extract sequence
            seq = esm_protein_to_sequence(
                sequence_result,
                prompt.num_residues,
            )
            seq_cid = f"seq-{context.run_id}-{i}"
            if sequence_source_classification == "prompt_reconstruction":
                validate_esm3_structure_response(
                    sequence_result,
                    expected_sequence=seq.sequence,
                    expected_length=prompt.num_residues,
                )
                esm_protein_to_scores(
                    sequence_result,
                    seq_cid,
                    require_structure_metrics=True,
                )
            seq_cand = Candidate(
                candidate_id=seq_cid,
                data=seq,
                parent_ids=[context.node_id],
                metadata=esm3_candidate_metadata(
                    model_name=model_name,
                    operation="generate(track=sequence)",
                    sample_index=i,
                    classification=sequence_source_classification,
                ),
            )
            seq_candidates.append(seq_cand)

            sampled_structure_prompt = structure_sampling_input(
                sequence_result,
                esm_protein,
            )
            structure_result = call_esm3_provider(
                client,
                sampled_structure_prompt,
                structure_config,
                "generate(track=structure)",
                context=context,
                model_name=model_name,
            )
            struct = esm_protein_to_structure(
                structure_result,
                expected_sequence=seq.sequence,
            )
            struct_cid = f"struct-{context.run_id}-{i}"
            struct_cand = Candidate(
                candidate_id=struct_cid,
                data=struct,
                parent_ids=[seq_cid],
                metadata=esm3_candidate_metadata(
                    model_name=model_name,
                    operation="generate(track=structure)",
                    sample_index=i,
                    classification="sampled_structure",
                ),
            )
            struct_candidates.append(struct_cand)

            # Scores reference the sequence candidate
            scores = esm_protein_to_scores(
                structure_result,
                seq_cid,
                require_structure_metrics=True,
            )
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
