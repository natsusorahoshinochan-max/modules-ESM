"""Shared remote ESM-3 implementation for all generation Nodes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.provider_contract import BIOHUB_ESM3_MODEL
from datatypes import Candidate, CandidateCollection, ProteinPrompt

from .adapter import (
    complete_sequence,
    generation_config,
    protein_prompt_to_provider,
    reject_silent_sequence_fields,
    require_provider_protein,
    response_has_structure,
)


class ESM3GenerationImplementation:
    """Dispatch all three public Nodes through one exact Adapter."""

    def __init__(
        self,
        run_resources: Any,
        operation: str,
        environment: Mapping[str, Any],
        catalog: Any,
    ) -> None:
        self._run_resources = run_resources
        self._operation = operation
        self._environment = environment
        self._catalog = catalog

    def _client(self) -> Any:
        client = self._environment.get("provider_client")
        if callable(getattr(client, "generate", None)):
            return client
        client_factory = self._environment.get("client_factory")
        if callable(client_factory):
            return client_factory(
                model_name=BIOHUB_ESM3_MODEL,
                endpoint_id=self._environment["endpoint_id"],
                credential_handle=self._environment["credential_handle"],
            )
        from modules.esm3_adapter import create_esm3_client

        return create_esm3_client(BIOHUB_ESM3_MODEL)

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
    ) -> Any:
        with self._run_resources.engine_invocation(
            engine_role=role,
            engine_identity=(
                f"esm3.biohub.{BIOHUB_ESM3_MODEL}.{operation}"
            ),
        ):
            result = client.generate(provider_prompt, config)
            return require_provider_protein(result, operation)

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
        if self._operation == "generate_sequence":
            return self._generate_sequence(prompt, parameters)
        raise NotImplementedError(
            f"ESM-3 operation {self._operation!r} is not implemented"
        )

    def _candidate_metadata(
        self,
        *,
        operation: str,
        sample_index: int,
        classification: str,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider": "biohub",
            "model": BIOHUB_ESM3_MODEL,
            "operation": operation,
            "sample_index": sample_index,
            "classification": classification,
            "effective_seed": parameters["effective_seed"],
            "seed_control": "unsupported_by_provider",
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
        config = generation_config("sequence", parameters)
        candidates: list[Candidate] = []
        structure_responses: list[tuple[int, Any, Candidate]] = []
        for sample_index in range(parameters["num_samples"]):
            result = self._provider_call(
                client,
                provider_prompt,
                config,
                role="sequence_sample",
                operation="generate_sequence",
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
            raise NotImplementedError(
                "coordinate-conditioned sequence reconstruction is not implemented"
            )
        return outputs
