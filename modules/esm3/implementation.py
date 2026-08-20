"""Canonical ESM-3 Scientific Operations behind route-specific Adapters."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any, cast

from core import (
    CandidatePairingIntent,
    CandidatePairingIntentEntry,
    OperationCall,
    builtin_frozen_catalog,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    ExactPortValueReference,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
)
from modules.structure_prediction.domain import (
    ConfidenceFact,
    ConfidenceFactCollection,
    PredictionResidueAxis,
    prediction_key,
)
from modules.structure_prediction.port_types import (
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
)
from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE

from .adapter import (
    ESM3CallParameters,
    ESM3Confidence,
    ESM3GenerationAdapter,
)


_BUILTINS = builtin_frozen_catalog()
_STRUCTURE_PORT_TYPE = _BUILTINS.require_port_type(
    "protein.structure",
    "4.0.0",
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
        prediction_key: str | None = None,
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
        if prediction_key is not None:
            metadata["prediction_key"] = prediction_key
        return metadata

    @staticmethod
    def _prompt_content_digest(call: OperationCall) -> str:
        return call.inputs["protein_prompt"].content_digest

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if set(call.inputs) != {"protein_prompt"} or call.binding_parameters:
            raise ValueError(
                "ESM-3 generation requires one ProteinPrompt and no Binding "
                "parameters"
            )
        prompt = call.inputs["protein_prompt"].value
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

    @staticmethod
    def _prompt_reference(prompt_content_digest: str) -> ExactPortValueReference:
        return ExactPortValueReference(
            port_type=ExactContractReference(
                contract_kind="port_type",
                contract_id=PROTEIN_PROMPT_PORT_TYPE.type_id,
                contract_version=PROTEIN_PROMPT_PORT_TYPE.version,
                contract_digest=PROTEIN_PROMPT_PORT_TYPE.contract_digest,
            ),
            content_digest=prompt_content_digest,
        )

    @staticmethod
    def _confidence_fact(
        *,
        output_role: str,
        output_slot: int,
        structure: ProteinStructure,
        prompt: ProteinPrompt,
        prompt_reference: ExactPortValueReference,
        sequence: ProteinSequence,
        confidence: ESM3Confidence,
    ) -> tuple[str, ConfidenceFact]:
        prediction_axis = PredictionResidueAxis(
            source=prompt_reference,
            layout=prompt.target_layout,
            sequence=sequence,
        )
        structure_content_digest = _STRUCTURE_PORT_TYPE.content_digest(
            structure
        )
        prediction_axis_content_digest = (
            PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(prediction_axis)
        )
        key = prediction_key(
            output_role=output_role,
            output_slot=output_slot,
            structure_content_digest=structure_content_digest,
            prediction_axis_content_digest=prediction_axis_content_digest,
        )
        return key, ConfidenceFact(
            prediction_key=key,
            structure_content_digest=structure_content_digest,
            prediction_axis=prediction_axis,
            plddt_per_residue=confidence.plddt_per_residue,
            ptm=confidence.ptm,
            pae=confidence.pae,
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
        reconstruction_facts: list[ConfidenceFact] = []
        prompt_reference = self._prompt_reference(prompt_content_digest)
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
                key, fact = self._confidence_fact(
                    output_role="sequence_reconstruction_candidates",
                    output_slot=len(reconstructions),
                    structure=result.reconstruction,
                    prompt=prompt,
                    prompt_reference=prompt_reference,
                    sequence=result.sequence,
                    confidence=cast(ESM3Confidence, result.confidence),
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
                        prediction_key=key,
                    ),
                )
                reconstructions.append(reconstruction)
                reconstruction_facts.append(fact)
        outputs: dict[str, Any] = {
            "sequence_candidates": CandidateCollection(
                "esm3-sequence-candidates",
                "protein.sequence",
                candidates,
            )
        }
        if reconstructions:
            outputs["sequence_reconstruction_candidates"] = (
                CandidateCollection(
                    "esm3-reconstructed-structures",
                    "protein.structure",
                    reconstructions,
                )
            )
            outputs["confidence_facts"] = ConfidenceFactCollection(
                observation_method=self._method,
                entries=tuple(reconstruction_facts),
            )
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
        self._assigned_prompt_sequence(prompt)
        candidates: list[Candidate] = []
        confidence_facts: list[ConfidenceFact] = []
        prompt_reference = self._prompt_reference(prompt_content_digest)
        for sample_index in range(num_samples):
            result = self._adapter.generate_structure(
                prompt,
                parameters=parameters,
                derived_call_seed=_derived_call_seed(
                    effective_seed,
                    prompt_content_digest,
                    sample_index,
                    "structure",
                ),
            )
            key, fact = self._confidence_fact(
                output_role="structure_candidates",
                output_slot=len(candidates),
                structure=result.structure,
                prompt=prompt,
                prompt_reference=prompt_reference,
                sequence=result.sequence,
                confidence=result.confidence,
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
                    prediction_key=key,
                ),
            )
            candidates.append(candidate)
            confidence_facts.append(fact)
        return {
            "structure_candidates": CandidateCollection(
                "esm3-structure-candidates",
                "protein.structure",
                candidates,
            ),
            "confidence_facts": ConfidenceFactCollection(
                observation_method=self._method,
                entries=tuple(confidence_facts),
            ),
        }

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
        confidence_facts: list[ConfidenceFact] = []
        reconstruction_candidates: list[Candidate] = []
        reconstruction_facts: list[ConfidenceFact] = []
        prompt_reference = self._prompt_reference(prompt_content_digest)
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
                reconstruction_key, reconstruction_fact = (
                    self._confidence_fact(
                        output_role="sequence_reconstruction_candidates",
                        output_slot=len(reconstruction_candidates),
                        structure=result.sequence.reconstruction,
                        prompt=prompt,
                        prompt_reference=prompt_reference,
                        sequence=result.sequence.sequence,
                        confidence=cast(
                            ESM3Confidence,
                            result.sequence.confidence,
                        ),
                    )
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
                        prediction_key=reconstruction_key,
                    ),
                )
                reconstruction_candidates.append(reconstruction)
                reconstruction_facts.append(reconstruction_fact)
            structure_key, structure_fact = self._confidence_fact(
                output_role="structure_candidates",
                output_slot=len(structure_candidates),
                structure=result.structure.structure,
                prompt=prompt,
                prompt_reference=prompt_reference,
                sequence=result.structure.sequence,
                confidence=result.structure.confidence,
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
                    prediction_key=structure_key,
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
            confidence_facts.append(structure_fact)
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
            "confidence_facts": ConfidenceFactCollection(
                observation_method=self._method,
                entries=tuple(confidence_facts),
            ),
        }
        if reconstruction_candidates:
            outputs["sequence_reconstruction_candidates"] = (
                CandidateCollection(
                    "esm3-paired-sequence-reconstructions",
                    "protein.structure",
                    reconstruction_candidates,
                )
            )
            outputs[
                "sequence_reconstruction_confidence_facts"
            ] = ConfidenceFactCollection(
                observation_method=self._method,
                entries=tuple(reconstruction_facts),
            )
        return outputs
