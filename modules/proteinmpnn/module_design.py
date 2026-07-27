"""ProteinMPNN Design: generates sequence candidates from a structure."""

import hashlib
import json
import uuid
from dataclasses import asdict
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
from modules.proteinmpnn.adapter import (
    ProteinMPNNProvider,
    design_sequences,
    validate_design_parameters,
)


class ProteinMPNNDesignModule(WorkflowModule):
    uses_seed = True

    def __init__(self, provider: ProteinMPNNProvider | None = None) -> None:
        d = Path(__file__).parent / "definition_design.yaml"
        self._definition = ModuleDefinition.from_yaml(d)
        self._provider = provider

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
        structures: CandidateCollection | None = inputs.get("structures")
        if (structure is None) == (structures is None):
            raise ValueError(
                "exactly one of 'structure' or 'structures' input is required"
            )
        parents: list[tuple[str, ProteinStructure]]
        if structure is not None:
            if not isinstance(structure, ProteinStructure):
                raise ValueError("structure input must be a ProteinStructure")
            parents = [(context.node_id, structure)]
        else:
            if not isinstance(structures, CandidateCollection):
                raise ValueError(
                    "structures input must be a CandidateCollection"
                )
            if structures.item_type != "protein.structure":
                raise ValueError(
                    "structures must contain protein.structure Candidates"
                )
            if not structures.items:
                raise ValueError("structures CandidateCollection is empty")
            parent_ids = [candidate.candidate_id for candidate in structures]
            if len(parent_ids) != len(set(parent_ids)):
                raise ValueError(
                    "structures CandidateCollection has duplicate Candidate IDs"
                )
            parents = []
            for candidate in structures:
                if not isinstance(candidate.data, ProteinStructure):
                    raise ValueError(
                        f"Candidate {candidate.candidate_id} data is not a "
                        "ProteinStructure"
                    )
                parents.append((candidate.candidate_id, candidate.data))

        constraints: ProteinMPNNConstraints | None = inputs.get("constraints")
        if constraints is not None and not isinstance(
            constraints, ProteinMPNNConstraints
        ):
            raise ValueError("constraints input must be ProteinMPNNConstraints")
        reference: ProteinSequence | None = inputs.get("sequence")
        if reference is not None and not isinstance(reference, ProteinSequence):
            raise ValueError("sequence input must be a ProteinSequence")

        model_name = str(parameters.get("model_name", "v_48_020"))
        num_sequences = int(parameters.get("num_sequences", 1))
        temperature = float(parameters.get("temperature", 0.1))
        backbone_noise = float(parameters.get("backbone_noise", 0.0))
        configured_seed = parameters.get("seed")
        effective_seed = (
            context.seed if configured_seed is None else configured_seed
        )
        validate_design_parameters(
            model_name,
            num_sequences,
            temperature,
            backbone_noise,
            effective_seed,
        )

        candidates: list[Candidate] = []
        all_scores: list[Score] = []
        effective_constraints = constraints or ProteinMPNNConstraints()
        constraint_payload = json.dumps(
            asdict(effective_constraints),
            sort_keys=True,
            separators=(",", ":"),
        )
        constraint_identity = (
            "sha256:"
            + hashlib.sha256(constraint_payload.encode()).hexdigest()
        )
        provider_identity = (
            self._provider.provider_identity
            if self._provider is not None
            else "local-proteinmpnn"
        )

        for parent_index, (parent_id, parent_structure) in enumerate(parents):
            candidate_ids = [
                f"mpnn-{context.run_id}-{parent_index}-{sample_index}"
                for sample_index in range(num_sequences)
            ]
            sequences, scores = design_sequences(
                pdb_string=parent_structure.pdb_string,
                model_name=model_name,
                num_sequences=num_sequences,
                temperature=temperature,
                backbone_noise=backbone_noise,
                seed=effective_seed,
                constraints=constraints,
                reference_sequence=(
                    reference.sequence if reference is not None else None
                ),
                provider=self._provider,
                temp_dir=context.temp_dir,
                call_details={
                    "parent_candidate_id": parent_id,
                    "candidate_ids": candidate_ids,
                    "effective_seed": effective_seed,
                },
            )
            for sample_index, (candidate_id, sequence, score) in enumerate(
                zip(candidate_ids, sequences, scores, strict=True)
            ):
                candidates.append(Candidate(
                    candidate_id=candidate_id,
                    data=sequence,
                    parent_ids=[parent_id],
                    metadata={
                        "model": model_name,
                        "provider": provider_identity,
                        "sample_index": sample_index,
                        "constraint_identity": constraint_identity,
                        "effective_seed": effective_seed,
                        "num_sequences": num_sequences,
                        "temperature": temperature,
                        "backbone_noise": backbone_noise,
                    },
                ))
                all_scores.append(Score(
                    score_id="proteinmpnn_score",
                    value=score,
                    subjects=[candidate_id],
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
