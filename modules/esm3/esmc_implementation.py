"""Run-scoped implementation of direct Biohub ESMC representation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datatypes import ProteinSequence

from .esmc_adapter import (
    BIOHUB_ESMC_MODEL,
    logits_config,
    normalize_representation,
    provider_sequence,
    require_provider_success,
)


class ESMCRepresentationImplementation:
    """Run the exact direct Biohub ESMC representation contract."""

    def __init__(
        self,
        run_resources: Any,
        environment: Mapping[str, Any],
        *,
        model_name: str = BIOHUB_ESMC_MODEL,
    ) -> None:
        self._run_resources = run_resources
        self._environment = environment
        self._model_name = model_name

    def _client(self) -> Any:
        client = self._environment.get("provider_client")
        if (
            callable(getattr(client, "encode", None))
            and callable(getattr(client, "logits", None))
        ):
            return client
        factory = self._environment.get("client_factory")
        if callable(factory):
            return factory(
                model_name=self._model_name,
                endpoint_id=self._environment["endpoint_id"],
                credential_handle=self._environment["credential_handle"],
            )
        raise RuntimeError(
            "Biohub ESMC requires an injected provider client or client factory"
        )

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            set(inputs) != {"sequence"}
            or node_parameters
            or binding_parameters
        ):
            raise ValueError(
                "direct ESMC representation requires one sequence and no "
                "parameters"
            )
        sequence = inputs["sequence"]
        if type(sequence) is not ProteinSequence:
            raise ValueError(
                "direct ESMC representation requires one ProteinSequence"
            )
        client = self._client()
        with self._run_resources.engine_invocation(
            engine_role="sequence_encode",
            engine_identity=f"esmc.biohub.{self._model_name}.encode",
        ):
            encoded = require_provider_success(
                client.encode(provider_sequence(sequence)),
                "encode",
            )
        with self._run_resources.engine_invocation(
            engine_role="sequence_logits",
            engine_identity=f"esmc.biohub.{self._model_name}.logits",
        ):
            result = require_provider_success(
                client.logits(encoded, logits_config()),
                "logits",
            )
        return {
            "representation": normalize_representation(
                sequence,
                result,
                model_name=self._model_name,
            )
        }
