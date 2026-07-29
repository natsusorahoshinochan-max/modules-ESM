"""Shared ESM-3 implementation for explicit remote and local Bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinPrompt,
    ProteinSequence,
    ProteinStructure,
)
from datatypes import (
    ExactContractReference,
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
)

from .adapter import (
    call_remote_provider,
    complete_sequence,
    complete_structure,
    derived_call_seed,
    generation_config,
    normalized_confidence,
    prepare_remote_provider_call,
    protein_prompt_to_provider,
    record_remote_provider_result,
    reject_silent_sequence_fields,
    response_has_structure,
    require_sequence_mask,
    structure_prompt_for_sequence,
)
from .local_adapter import (
    call_local_provider,
    load_local_esm3_client,
    prepare_local_provider_call,
    record_local_provider_result,
    release_local_esm3_client,
    resolve_local_runtime,
)


class ESM3GenerationImplementation:
    """Dispatch all three public Nodes through one exact Adapter."""

    def __init__(
        self,
        run_resources: Any,
        operation: str,
        environment: Mapping[str, Any],
        catalog: Any,
        *,
        model_name: str,
        method_id: str,
        route_name: str = "biohub",
        seed_control: str = "unsupported_by_provider",
    ) -> None:
        self._run_resources = run_resources
        self._operation = operation
        self._environment = environment
        self._catalog = catalog
        self._model_name = model_name
        self._method_id = method_id
        self._route_name = route_name
        self._seed_control = seed_control
        self._runtime_fingerprint: str | None = None
        self._owned_local_client: Any | None = None

    def _client(self) -> Any:
        if self._route_name == "local_open":
            runtime = resolve_local_runtime(self._environment)
            self._runtime_fingerprint = runtime.safe_fingerprint
            client = self._environment.get("provider_client")
            if callable(getattr(client, "generate", None)):
                return client
            client_factory = self._environment.get("client_factory")
            if callable(client_factory):
                return client_factory(
                    model_name=self._model_name,
                    model_snapshot_path=runtime.snapshot_path,
                    device=runtime.device,
                    runtime_directory=runtime.runtime_directory,
                    performance_settings=dict(runtime.performance_settings),
                )
            client = load_local_esm3_client(
                self._environment,
                model_name=self._model_name,
                runtime=runtime,
            )
            self._owned_local_client = client
            return client
        client = self._environment.get("provider_client")
        if callable(getattr(client, "generate", None)):
            return client
        client_factory = self._environment.get("client_factory")
        if callable(client_factory):
            return client_factory(
                model_name=self._model_name,
                endpoint_id=self._environment["endpoint_id"],
                credential_handle=self._environment["credential_handle"],
            )
        raise RuntimeError(
            "remote ESM-3 requires an injected provider client or client "
            "factory"
        )

    @staticmethod
    def _parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
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
        return dict(parameters)

    def _provider_call(
        self,
        client: Any,
        provider_prompt: Any,
        config: Any,
        *,
        role: str,
        operation: str,
        parent_invocation_id: str | None = None,
        effective_call_seed: int,
    ) -> tuple[Any, str]:
        provider_operation = {
            "generate_sequence": "generate(track=sequence)",
            "generate_structure": "generate(track=structure)",
        }[operation]
        if self._route_name == "local_open":
            if self._runtime_fingerprint is None:
                raise RuntimeError(
                    "local ESM-3 runtime was not resolved before invocation"
                )
            track_identity = prepare_local_provider_call(
                provider_prompt,
                provider_operation,
                model_name=self._model_name,
                effective_seed=effective_call_seed,
                runtime_fingerprint=self._runtime_fingerprint,
            )
        else:
            track_identity = prepare_remote_provider_call(
                provider_prompt,
                provider_operation,
                model_name=self._model_name,
            )
        with self._run_resources.engine_invocation(
            engine_role=role,
            engine_identity=(
                f"esm3.{self._route_name}.{self._model_name}.{operation}"
            ),
            parent_invocation_id=parent_invocation_id,
        ) as invocation_id:
            if self._route_name == "local_open":
                result = call_local_provider(
                    client,
                    provider_prompt,
                    config,
                    provider_operation,
                    effective_seed=effective_call_seed,
                )
            else:
                result = call_remote_provider(
                    client,
                    provider_prompt,
                    config,
                    provider_operation,
                )
        if self._route_name == "local_open":
            assert self._runtime_fingerprint is not None
            record_local_provider_result(
                provider_prompt,
                result,
                provider_operation,
                model_name=self._model_name,
                effective_seed=effective_call_seed,
                track_identity=track_identity,
            )
        else:
            record_remote_provider_result(
                provider_prompt,
                result,
                provider_operation,
                model_name=self._model_name,
                track_identity=track_identity,
            )
        return result, invocation_id

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if set(inputs) != {"protein_prompt"} or binding_parameters:
            raise ValueError(
                "ESM-3 generation requires one ProteinPrompt and no route "
                "parameters"
            )
        prompt = inputs["protein_prompt"]
        if type(prompt) is not ProteinPrompt:
            raise ValueError("protein_prompt has the wrong runtime type")
        parameters = self._parameters(node_parameters)
        try:
            if self._operation == "generate_sequence":
                outputs = self._generate_sequence(prompt, parameters)
            elif self._operation == "generate_structure":
                outputs = self._generate_structure(prompt, parameters)
            elif self._operation == "generate_paired":
                outputs = self._generate_paired(prompt, parameters)
            else:
                raise NotImplementedError(
                    f"ESM-3 operation {self._operation!r} is not implemented"
                )
        except BaseException as body_error:
            self._release_owned_local_client(body_error=body_error)
            raise
        self._release_owned_local_client()
        return outputs

    def _release_owned_local_client(
        self,
        *,
        body_error: BaseException | None = None,
    ) -> None:
        client = self._owned_local_client
        self._owned_local_client = None
        if client is None:
            return
        try:
            release_local_esm3_client(client)
        except BaseException as cleanup_error:
            if body_error is None:
                raise
            body_error.add_note(
                "Local ESM-3 staged-weight cleanup also failed: "
                f"{type(cleanup_error).__name__}"
            )

    def _candidate_metadata(
        self,
        *,
        operation: str,
        sample_index: int,
        classification: str,
        parameters: Mapping[str, Any],
        call_track: str,
    ) -> dict[str, Any]:
        return {
            "provider": self._route_name,
            "model": self._model_name,
            "operation": operation,
            "sample_index": sample_index,
            "classification": classification,
            "effective_seed": parameters["effective_seed"],
            "effective_call_seed": derived_call_seed(
                parameters["effective_seed"],
                sample_index,
                call_track,
            ),
            "effective_call_seed_scope": "sample_and_track",
            "seed_control": self._seed_control,
            "generation_parameters": {
                name: parameters[name]
                for name in (
                    "num_steps",
                    "temperature",
                    "top_p",
                    "schedule",
                    "strategy",
                    "temperature_annealing",
                )
            },
        }

    def _generate_sequence(
        self,
        prompt: ProteinPrompt,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        client = self._client()
        provider_prompt = protein_prompt_to_provider(prompt)
        require_sequence_mask(provider_prompt)
        config = generation_config("sequence", parameters)
        candidates: list[Candidate] = []
        structure_responses: list[tuple[int, Any, Candidate]] = []
        for sample_index in range(parameters["num_samples"]):
            result, _ = self._provider_call(
                client,
                provider_prompt,
                config,
                role="sequence_sample",
                operation="generate_sequence",
                effective_call_seed=derived_call_seed(
                    parameters["effective_seed"],
                    sample_index,
                    "sequence",
                ),
            )
            sequence = complete_sequence(result, prompt)
            raw_id = f"sequence-{sample_index}"
            candidate = Candidate(
                raw_id,
                sequence,
                [],
                self._candidate_metadata(
                    operation="generate_sequence",
                    sample_index=sample_index,
                    classification="sequence",
                    parameters=parameters,
                    call_track="sequence",
                ),
            )
            candidates.append(candidate)
            if response_has_structure(result):
                structure_responses.append((sample_index, result, candidate))
            else:
                reject_silent_sequence_fields(result)
        outputs: dict[str, Any] = {
            "sequence_candidates": CandidateCollection(
                "esm3-sequence-candidates",
                "protein.sequence",
                candidates,
            )
        }
        if structure_responses:
            if getattr(provider_prompt, "coordinates", None) is None:
                raise ValueError(
                    "sequence generation returned structure fields without "
                    "coordinate-conditioned input"
                )
            reconstructed: list[Candidate] = []
            confidence_sources: list[tuple[Candidate, Any]] = []
            for sample_index, response, sequence_candidate in structure_responses:
                structure = complete_structure(
                    response,
                    prompt,
                    expected_sequence=sequence_candidate.data.sequence,
                )
                structure_candidate = Candidate(
                    f"reconstructed-structure-{sample_index}",
                    structure,
                    [sequence_candidate.candidate_id],
                    self._candidate_metadata(
                        operation="generate_sequence",
                        sample_index=sample_index,
                        classification="prompt_reconstruction",
                        parameters=parameters,
                        call_track="sequence",
                    ),
                )
                reconstructed.append(structure_candidate)
                confidence_sources.append((structure_candidate, response))
            confidence, pae = self._confidence_outputs(confidence_sources)
            outputs["sequence_reconstruction_candidates"] = CandidateCollection(
                "esm3-reconstructed-structures",
                "protein.structure",
                reconstructed,
            )
            outputs["confidence_observations"] = confidence
            if pae is not None:
                outputs["pae_observations"] = pae
        return outputs

    def _contract_reference(
        self,
        kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        contract = self._catalog.require_contract(
            kind,
            contract_id,
            "2.0.0",
        )
        return ExactContractReference(**contract.reference())

    def _confidence_outputs(
        self,
        responses: list[tuple[Candidate, Any]],
        *,
        output_partition: str = "structure_confidence",
    ) -> tuple[ScoreCollection, ScoreCollection | None]:
        method = self._contract_reference(
            "method",
            self._method_id,
        )
        metric_references = {
            metric_id: self._contract_reference("metric", metric_id)
            for metric_id in (
                "structure.ptm",
                "structure.plddt.per_residue",
                "structure.plddt.mean_residue",
                "structure.pae",
            )
        }
        confidence: list[ScoreObservation] = []
        pae_observations: list[ScoreObservation] = []
        for candidate, response in responses:
            sequence = getattr(response, "sequence")
            ptm, per_residue, mean_residue, pae = normalized_confidence(
                response,
                residue_count=len(sequence),
            )
            for metric_id, value in (
                ("structure.ptm", ptm),
                ("structure.plddt.per_residue", per_residue),
                ("structure.plddt.mean_residue", mean_residue),
            ):
                confidence.append(
                    ScoreObservation(
                        candidate_id=candidate.candidate_id,
                        metric=metric_references[metric_id],
                        method=method,
                        context=IntrinsicObservationContext(),
                        value=value,
                        source_partition=output_partition,
                    )
                )
            if pae is not None:
                pae_observations.append(
                    ScoreObservation(
                        candidate_id=candidate.candidate_id,
                        metric=metric_references["structure.pae"],
                        method=method,
                        context=IntrinsicObservationContext(),
                        value=pae,
                        source_partition=output_partition,
                    )
                )
        return (
            ScoreCollection("esm3-confidence", confidence),
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

    def _generate_structure(
        self,
        prompt: ProteinPrompt,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        expected_sequence = self._assigned_prompt_sequence(prompt)
        client = self._client()
        provider_prompt = protein_prompt_to_provider(prompt)
        config = generation_config("structure", parameters)
        candidates: list[Candidate] = []
        confidence_sources: list[tuple[Candidate, Any]] = []
        for sample_index in range(parameters["num_samples"]):
            result, _ = self._provider_call(
                client,
                provider_prompt,
                config,
                role="structure_sample",
                operation="generate_structure",
                effective_call_seed=derived_call_seed(
                    parameters["effective_seed"],
                    sample_index,
                    "structure",
                ),
            )
            structure = complete_structure(
                result,
                prompt,
                expected_sequence=expected_sequence,
            )
            candidate = Candidate(
                f"structure-{sample_index}",
                structure,
                [],
                self._candidate_metadata(
                    operation="generate_structure",
                    sample_index=sample_index,
                    classification="sampled_structure",
                    parameters=parameters,
                    call_track="structure",
                ),
            )
            candidates.append(candidate)
            confidence_sources.append((candidate, result))
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

    def _content_digest(self, candidate: Candidate) -> str:
        if type(candidate.data) is ProteinSequence:
            type_id = "protein.sequence"
        elif type(candidate.data) is ProteinStructure:
            type_id = "protein.structure"
        else:
            raise TypeError(
                "ESM-3 paired content must be a sequence or structure"
            )
        return self._catalog.require_port_type(
            type_id,
            "2.0.0",
        ).content_digest(candidate.data)

    def _generate_paired(
        self,
        prompt: ProteinPrompt,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        client = self._client()
        provider_prompt = protein_prompt_to_provider(prompt)
        require_sequence_mask(provider_prompt)
        sequence_config = generation_config("sequence", parameters)
        structure_config = generation_config("structure", parameters)
        sequence_candidates: list[Candidate] = []
        structure_candidates: list[Candidate] = []
        pairing_entries: list[PairwiseCandidateMatch] = []
        confidence_sources: list[tuple[Candidate, Any]] = []
        reconstruction_candidates: list[Candidate] = []
        reconstruction_confidence_sources: list[tuple[Candidate, Any]] = []
        for sample_index in range(parameters["num_samples"]):
            sequence_result, sequence_invocation_id = self._provider_call(
                client,
                provider_prompt,
                sequence_config,
                role="sequence_parent",
                operation="generate_sequence",
                effective_call_seed=derived_call_seed(
                    parameters["effective_seed"],
                    sample_index,
                    "sequence",
                ),
            )
            sequence = complete_sequence(sequence_result, prompt)
            sequence_candidate = Candidate(
                f"sequence-{sample_index}",
                sequence,
                [],
                self._candidate_metadata(
                    operation="generate_sequence",
                    sample_index=sample_index,
                    classification="sequence",
                    parameters=parameters,
                    call_track="sequence",
                ),
            )
            if response_has_structure(sequence_result):
                if getattr(provider_prompt, "coordinates", None) is None:
                    raise ValueError(
                        "paired sequence generation returned structure fields "
                        "without coordinate-conditioned input"
                    )
                reconstruction_candidate = Candidate(
                    f"reconstructed-structure-{sample_index}",
                    complete_structure(
                        sequence_result,
                        prompt,
                        expected_sequence=sequence.sequence,
                    ),
                    [sequence_candidate.candidate_id],
                    self._candidate_metadata(
                        operation="generate_sequence",
                        sample_index=sample_index,
                        classification="prompt_reconstruction",
                        parameters=parameters,
                        call_track="sequence",
                    ),
                )
                reconstruction_candidates.append(reconstruction_candidate)
                reconstruction_confidence_sources.append(
                    (reconstruction_candidate, sequence_result)
                )
            else:
                reject_silent_sequence_fields(sequence_result)
            structure_prompt = structure_prompt_for_sequence(
                provider_prompt,
                sequence.sequence,
            )
            structure_result, _ = self._provider_call(
                client,
                structure_prompt,
                structure_config,
                role="structure_child",
                operation="generate_structure",
                parent_invocation_id=sequence_invocation_id,
                effective_call_seed=derived_call_seed(
                    parameters["effective_seed"],
                    sample_index,
                    "structure",
                ),
            )
            structure = complete_structure(
                structure_result,
                prompt,
                expected_sequence=sequence.sequence,
            )
            structure_candidate = Candidate(
                f"structure-{sample_index}",
                structure,
                [sequence_candidate.candidate_id],
                self._candidate_metadata(
                    operation="generate_structure",
                    sample_index=sample_index,
                    classification="sampled_structure",
                    parameters=parameters,
                    call_track="structure",
                ),
            )
            sequence_candidates.append(sequence_candidate)
            structure_candidates.append(structure_candidate)
            pairing_entries.append(
                PairwiseCandidateMatch(
                    subject_candidate_id=sequence_candidate.candidate_id,
                    subject_content_digest=self._content_digest(
                        sequence_candidate
                    ),
                    reference_candidate_id=structure_candidate.candidate_id,
                    reference_content_digest=self._content_digest(
                        structure_candidate
                    ),
                )
            )
            confidence_sources.append(
                (structure_candidate, structure_result)
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
            "counterpart_pairs": PairwiseCandidateMapping(pairing_entries),
            "confidence_observations": confidence,
        }
        if pae is not None:
            outputs["pae_observations"] = pae
        if reconstruction_candidates:
            reconstruction_confidence, reconstruction_pae = (
                self._confidence_outputs(
                    reconstruction_confidence_sources,
                    output_partition="sequence_reconstruction_confidence",
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
            ] = reconstruction_confidence
            if reconstruction_pae is not None:
                outputs[
                    "sequence_reconstruction_pae_observations"
                ] = reconstruction_pae
        return outputs
