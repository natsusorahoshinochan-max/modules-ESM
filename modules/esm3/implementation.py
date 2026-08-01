"""Canonical ESM-3 Scientific Operations behind route-specific Adapters."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math
from typing import Any

from core import (
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    OperationCall,
    ResolvedProducedObservation,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinPrompt,
    ScoreCollection,
    ScoreObservation,
)

from .adapter import (
    ESM3CallParameters,
    ESM3Confidence,
    ESM3GenerationAdapter,
)


def _derived_call_seed(
    effective_seed: int,
    prompt_content_digest: str,
    sample_index: int,
    track: str,
) -> int:
    """Derive the stable scientific identity for one sample/track slot."""
    digest = hashlib.sha256(
        (
            "protein-workbench-esm3-call-seed/v2:"
            f"{effective_seed}:{prompt_content_digest}:{sample_index}:{track}"
        ).encode("ascii")
    ).digest()
    return int.from_bytes(digest[:6], "big")


class ESM3GenerationOperation:
    """Own ESM-3 sampling semantics above one provider Adapter seam."""

    def __init__(
        self,
        *,
        adapter: ESM3GenerationAdapter,
        operation: str,
        method: ExactContractReference,
        produced_observations: tuple[ResolvedProducedObservation, ...],
    ) -> None:
        if operation not in {
            "generate_sequence",
            "generate_structure",
            "generate_paired",
        }:
            raise ValueError("ESM-3 Operation identity is not declared")
        self._adapter = adapter
        self._operation = operation
        self._method = method
        self._produced_observations = {
            (observation.output_port, observation.metric.contract_id): (
                observation
            )
            for observation in produced_observations
        }

    @staticmethod
    def _parameters(
        parameters: Mapping[str, Any],
    ) -> tuple[int, int, ESM3CallParameters]:
        expected = {
            "effective_seed",
            "num_samples",
            "num_steps",
            "temperature",
            "top_p",
            "schedule",
            "strategy",
            "temperature_annealing",
        }
        if set(parameters) != expected:
            raise ValueError(
                "ESM-3 generation parameters are not fully resolved"
            )
        return (
            parameters["effective_seed"],
            parameters["num_samples"],
            ESM3CallParameters(
                num_steps=parameters["num_steps"],
                temperature=parameters["temperature"],
                top_p=parameters["top_p"],
                schedule=parameters["schedule"],
                strategy=parameters["strategy"],
                temperature_annealing=parameters[
                    "temperature_annealing"
                ],
            ),
        )

    @staticmethod
    def _requested_parameters(
        parameters: ESM3CallParameters,
    ) -> dict[str, Any]:
        return {
            "num_steps": parameters.num_steps,
            "temperature": parameters.temperature,
            "top_p": parameters.top_p,
            "schedule": parameters.schedule,
            "strategy": parameters.strategy,
            "temperature_annealing": parameters.temperature_annealing,
        }

    @classmethod
    def _candidate_metadata(
        cls,
        *,
        operation: str,
        sample_index: int,
        classification: str,
        configured_base_seed: int,
        parameters: ESM3CallParameters,
        call_track: str,
        effective_call_seed: int | None,
        effective_num_steps: int,
        effective_num_steps_by_track: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        requested = cls._requested_parameters(parameters)
        steps_by_track = (
            dict(effective_num_steps_by_track)
            if effective_num_steps_by_track is not None
            else {call_track: effective_num_steps}
        )
        metadata = {
            "operation": operation,
            "sample_index": sample_index,
            "classification": classification,
            "requested_generation_parameters": requested,
            "effective_generation_parameters": {
                track: {
                    **requested,
                    "num_steps": steps,
                }
                for track, steps in steps_by_track.items()
            },
        }
        if effective_call_seed is not None:
            metadata.update(
                {
                    "configured_base_seed": configured_base_seed,
                    "effective_call_seed": effective_call_seed,
                    "effective_call_seed_scope": (
                        "scientific-input-content-and-sample-track-slot"
                    ),
                }
            )
        return metadata

    @staticmethod
    def _prompt_content_digest(call: OperationCall) -> str:
        digest_set = call.input_content_digests.get("protein_prompt")
        if (
            digest_set is None
            or digest_set.port_type_id != "protein.prompt"
            or len(digest_set.value_content_digests) != 1
            or digest_set.candidate_data
        ):
            raise ValueError(
                "ESM-3 generation requires one admitted ProteinPrompt "
                "content identity"
            )
        return digest_set.value_content_digests[0]

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if set(call.inputs) != {"protein_prompt"} or call.binding_parameters:
            raise ValueError(
                "ESM-3 generation requires one ProteinPrompt and no Binding "
                "parameters"
            )
        prompt = call.inputs["protein_prompt"]
        if type(prompt) is not ProteinPrompt:
            raise ValueError("protein_prompt has the wrong runtime type")
        effective_seed, num_samples, parameters = self._parameters(
            call.node_parameters
        )
        prompt_content_digest = self._prompt_content_digest(call)
        with self._adapter:
            if self._operation == "generate_sequence":
                return self._generate_sequence(
                    prompt,
                    effective_seed=effective_seed,
                    prompt_content_digest=prompt_content_digest,
                    num_samples=num_samples,
                    parameters=parameters,
                )
            if self._operation == "generate_structure":
                return self._generate_structure(
                    prompt,
                    effective_seed=effective_seed,
                    prompt_content_digest=prompt_content_digest,
                    num_samples=num_samples,
                    parameters=parameters,
                )
            return self._generate_paired(
                prompt,
                effective_seed=effective_seed,
                prompt_content_digest=prompt_content_digest,
                num_samples=num_samples,
                parameters=parameters,
            )

    def _produced_observation(
        self,
        metric_id: str,
        *,
        output_port: str,
    ) -> ResolvedProducedObservation:
        return self._produced_observations[(output_port, metric_id)]

    def _confidence_outputs(
        self,
        sources: list[tuple[Candidate, ESM3Confidence]],
        *,
        confidence_output_port: str = "confidence_observations",
        pae_output_port: str = "pae_observations",
    ) -> tuple[ScoreCollection, ScoreCollection | None]:
        produced_observations = {
            metric_id: self._produced_observation(
                metric_id,
                output_port=(
                    pae_output_port
                    if metric_id == "structure.pae"
                    else confidence_output_port
                ),
            )
            for metric_id in (
                "structure.ptm",
                "structure.plddt.per_residue",
                "structure.plddt.mean_residue",
                "structure.pae",
            )
        }
        confidence_observations: list[ScoreObservation] = []
        pae_observations: list[ScoreObservation] = []
        for candidate, confidence in sources:
            for metric_id, value in (
                ("structure.ptm", confidence.ptm),
                (
                    "structure.plddt.per_residue",
                    confidence.plddt_per_residue,
                ),
                (
                    "structure.plddt.mean_residue",
                    math.fsum(confidence.plddt_per_residue)
                    / len(confidence.plddt_per_residue),
                ),
            ):
                produced = produced_observations[metric_id]
                confidence_observations.append(
                    ScoreObservation(
                        candidate_id=candidate.candidate_id,
                        metric=produced.metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=value,
                        source_partition=produced.output_partition,
                    )
                )
            if confidence.pae is not None:
                produced = produced_observations["structure.pae"]
                pae_observations.append(
                    ScoreObservation(
                        candidate_id=candidate.candidate_id,
                        metric=produced.metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=confidence.pae,
                        source_partition=produced.output_partition,
                    )
                )
        return (
            ScoreCollection("esm3-confidence", confidence_observations),
            (
                ScoreCollection("esm3-pae", pae_observations)
                if pae_observations
                else None
            ),
        )

    @staticmethod
    def _assigned_prompt_sequence(prompt: ProteinPrompt) -> str:
        track = prompt.sequence_track
        if (
            track is None
            or len(track.values) != prompt.num_residues
            or any(
                type(value) is not str or value == "_"
                for value in track.values
            )
        ):
            raise ValueError(
                "structure generation requires a complete assigned sequence"
            )
        return "".join(track.values)

    def _generate_sequence(
        self,
        prompt: ProteinPrompt,
        *,
        effective_seed: int,
        prompt_content_digest: str,
        num_samples: int,
        parameters: ESM3CallParameters,
    ) -> dict[str, Any]:
        candidates: list[Candidate] = []
        reconstructions: list[Candidate] = []
        reconstruction_confidence: list[tuple[Candidate, ESM3Confidence]] = []
        for sample_index in range(num_samples):
            call_seed = _derived_call_seed(
                effective_seed,
                prompt_content_digest,
                sample_index,
                "sequence",
            )
            result = self._adapter.generate_sequence(
                prompt,
                parameters=parameters,
                derived_call_seed=call_seed,
            )
            candidate = Candidate(
                f"sequence-{sample_index}",
                result.sequence,
                [],
                self._candidate_metadata(
                    operation="generate_sequence",
                    sample_index=sample_index,
                    classification="sequence",
                    configured_base_seed=effective_seed,
                    parameters=parameters,
                    call_track="sequence",
                    effective_call_seed=result.effective_call_seed,
                    effective_num_steps=result.effective_num_steps,
                ),
            )
            candidates.append(candidate)
            if result.reconstruction is not None:
                if result.confidence is None:
                    raise RuntimeError(
                        "ESM-3 reconstruction confidence is incomplete"
                    )
                reconstruction = Candidate(
                    f"reconstructed-structure-{sample_index}",
                    result.reconstruction,
                    [candidate.candidate_id],
                    self._candidate_metadata(
                        operation="generate_sequence",
                        sample_index=sample_index,
                        classification="prompt_reconstruction",
                        configured_base_seed=effective_seed,
                        parameters=parameters,
                        call_track="sequence",
                        effective_call_seed=result.effective_call_seed,
                        effective_num_steps=result.effective_num_steps,
                    ),
                )
                reconstructions.append(reconstruction)
                reconstruction_confidence.append(
                    (reconstruction, result.confidence)
                )
        outputs: dict[str, Any] = {
            "sequence_candidates": CandidateCollection(
                "esm3-sequence-candidates",
                "protein.sequence",
                candidates,
            )
        }
        if reconstructions:
            confidence, pae = self._confidence_outputs(
                reconstruction_confidence
            )
            outputs["sequence_reconstruction_candidates"] = (
                CandidateCollection(
                    "esm3-reconstructed-structures",
                    "protein.structure",
                    reconstructions,
                )
            )
            outputs["confidence_observations"] = confidence
            if pae is not None:
                outputs["pae_observations"] = pae
        return outputs

    def _generate_structure(
        self,
        prompt: ProteinPrompt,
        *,
        effective_seed: int,
        prompt_content_digest: str,
        num_samples: int,
        parameters: ESM3CallParameters,
    ) -> dict[str, Any]:
        expected_sequence = self._assigned_prompt_sequence(prompt)
        candidates: list[Candidate] = []
        confidence_sources: list[tuple[Candidate, ESM3Confidence]] = []
        for sample_index in range(num_samples):
            result = self._adapter.generate_structure(
                prompt,
                expected_sequence=expected_sequence,
                parameters=parameters,
                derived_call_seed=_derived_call_seed(
                    effective_seed,
                    prompt_content_digest,
                    sample_index,
                    "structure",
                ),
            )
            candidate = Candidate(
                f"structure-{sample_index}",
                result.structure,
                [],
                self._candidate_metadata(
                    operation="generate_structure",
                    sample_index=sample_index,
                    classification="sampled_structure",
                    configured_base_seed=effective_seed,
                    parameters=parameters,
                    call_track="structure",
                    effective_call_seed=result.effective_call_seed,
                    effective_num_steps=result.effective_num_steps,
                ),
            )
            candidates.append(candidate)
            confidence_sources.append((candidate, result.confidence))
        confidence, pae = self._confidence_outputs(confidence_sources)
        outputs: dict[str, Any] = {
            "structure_candidates": CandidateCollection(
                "esm3-structure-candidates",
                "protein.structure",
                candidates,
            ),
            "confidence_observations": confidence,
        }
        if pae is not None:
            outputs["pae_observations"] = pae
        return outputs

    def _generate_paired(
        self,
        prompt: ProteinPrompt,
        *,
        effective_seed: int,
        prompt_content_digest: str,
        num_samples: int,
        parameters: ESM3CallParameters,
    ) -> dict[str, Any]:
        sequence_candidates: list[Candidate] = []
        structure_candidates: list[Candidate] = []
        pairing_entries: list[CandidatePairingIntentEntry] = []
        confidence_sources: list[tuple[Candidate, ESM3Confidence]] = []
        reconstruction_candidates: list[Candidate] = []
        reconstruction_confidence: list[tuple[Candidate, ESM3Confidence]] = []
        for sample_index in range(num_samples):
            result = self._adapter.generate_pair(
                prompt,
                parameters=parameters,
                sequence_derived_call_seed=_derived_call_seed(
                    effective_seed,
                    prompt_content_digest,
                    sample_index,
                    "sequence",
                ),
                structure_derived_call_seed=_derived_call_seed(
                    effective_seed,
                    prompt_content_digest,
                    sample_index,
                    "structure",
                ),
            )
            sequence_candidate = Candidate(
                f"sequence-{sample_index}",
                result.sequence.sequence,
                [],
                self._candidate_metadata(
                    operation="generate_sequence",
                    sample_index=sample_index,
                    classification="sequence",
                    configured_base_seed=effective_seed,
                    parameters=parameters,
                    call_track="sequence",
                    effective_call_seed=(
                        result.sequence.effective_call_seed
                    ),
                    effective_num_steps=result.sequence.effective_num_steps,
                ),
            )
            if result.sequence.reconstruction is not None:
                if result.sequence.confidence is None:
                    raise RuntimeError(
                        "ESM-3 reconstruction confidence is incomplete"
                    )
                reconstruction = Candidate(
                    f"reconstructed-structure-{sample_index}",
                    result.sequence.reconstruction,
                    [sequence_candidate.candidate_id],
                    self._candidate_metadata(
                        operation="generate_sequence",
                        sample_index=sample_index,
                        classification="prompt_reconstruction",
                        configured_base_seed=effective_seed,
                        parameters=parameters,
                        call_track="sequence",
                        effective_call_seed=(
                            result.sequence.effective_call_seed
                        ),
                        effective_num_steps=(
                            result.sequence.effective_num_steps
                        ),
                    ),
                )
                reconstruction_candidates.append(reconstruction)
                reconstruction_confidence.append(
                    (reconstruction, result.sequence.confidence)
                )
            structure_candidate = Candidate(
                f"structure-{sample_index}",
                result.structure.structure,
                [sequence_candidate.candidate_id],
                self._candidate_metadata(
                    operation="generate_structure",
                    sample_index=sample_index,
                    classification="sampled_structure",
                    configured_base_seed=effective_seed,
                    parameters=parameters,
                    call_track="structure",
                    effective_call_seed=(
                        result.structure.effective_call_seed
                    ),
                    effective_num_steps=(
                        result.structure.effective_num_steps
                    ),
                    effective_num_steps_by_track={
                        "sequence": result.sequence.effective_num_steps,
                        "structure": result.structure.effective_num_steps,
                    },
                ),
            )
            sequence_candidates.append(sequence_candidate)
            structure_candidates.append(structure_candidate)
            pairing_entries.append(
                CandidatePairingIntentEntry(
                    subject_candidate_id=sequence_candidate.candidate_id,
                    reference_candidate_id=structure_candidate.candidate_id,
                )
            )
            confidence_sources.append(
                (structure_candidate, result.structure.confidence)
            )
        confidence, pae = self._confidence_outputs(confidence_sources)
        outputs: dict[str, Any] = {
            "sequence_candidates": CandidateCollection(
                "esm3-paired-sequences",
                "protein.sequence",
                sequence_candidates,
            ),
            "structure_candidates": CandidateCollection(
                "esm3-paired-structures",
                "protein.structure",
                structure_candidates,
            ),
            "counterpart_pairs": CandidatePairingIntent(pairing_entries),
            "confidence_observations": confidence,
        }
        if pae is not None:
            outputs["pae_observations"] = pae
        if reconstruction_candidates:
            reconstruction_scores, reconstruction_pae = (
                self._confidence_outputs(
                    reconstruction_confidence,
                    confidence_output_port=(
                        "sequence_reconstruction_confidence_observations"
                    ),
                    pae_output_port=(
                        "sequence_reconstruction_pae_observations"
                    ),
                )
            )
            outputs["sequence_reconstruction_candidates"] = (
                CandidateCollection(
                    "esm3-paired-sequence-reconstructions",
                    "protein.structure",
                    reconstruction_candidates,
                )
            )
            outputs[
                "sequence_reconstruction_confidence_observations"
            ] = reconstruction_scores
            if reconstruction_pae is not None:
                outputs[
                    "sequence_reconstruction_pae_observations"
                ] = reconstruction_pae
        return outputs
