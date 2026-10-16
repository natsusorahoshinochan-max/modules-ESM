"""Exact Protein Workbench adapter for Biohub ESMC sequence inference."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.operation import OperationResources
from datatypes.sequence import ProteinSequence

from .domain import ESMCSequenceRepresentation


BIOHUB_ESMC_MODEL = "esmc-600m-2024-12"


def build_biohub_esmc_client(
    *,
    model_name: str,
    credential_handle: object,
    service_url: str,
) -> Any:
    """Construct the configured SDK client from trusted deployment values."""
    from esm.sdk import esmc_client

    return esmc_client(
        model=model_name,
        url=service_url,
        token=credential_handle,
        request_timeout=150,
    )


def provider_sequence(sequence: ProteinSequence) -> Any:
    """Translate one complete canonical sequence without changing its axis."""
    from esm.sdk.api import ESMProtein

    return ESMProtein(sequence=sequence.sequence)


def logits_config(*, embedding: bool, logits: bool) -> Any:
    """Request the minimal scientific ESMC representation and real logits."""
    from esm.sdk.api import LogitsConfig

    return LogitsConfig(
        sequence=logits,
        return_mean_embedding=embedding,
    )


def require_provider_success(value: Any, operation: str) -> Any:
    """Reject SDK provider-error values before any result normalization."""
    from esm.sdk.api import ESMProteinError

    if isinstance(value, ESMProteinError):
        raise RuntimeError(f"Biohub ESMC {operation} failed")
    return value


def normalize_representation(
    sequence: ProteinSequence,
    result: Any,
) -> ESMCSequenceRepresentation:
    """Translate Provider tensors into the canonical value once."""
    return ESMCSequenceRepresentation(
        sequence=sequence.sequence,
        residue_ids=sequence.residue_ids,
        mean_embedding=(None if result.mean_embedding is None else tuple(
            float(value) for value in result.mean_embedding[0, 0].detach().cpu().tolist()
        )),
        sequence_logits=(None if result.logits.sequence is None else tuple(
            tuple(float(value) for value in row)
            for row in result.logits.sequence[1:-1].detach().cpu().tolist()
        )),
    )


class BiohubESMCAdapter:
    """Translate and admit the exact two-call Biohub ESMC operation."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: OperationResources,
        model_name: str,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._model_name = model_name

    def _client(self) -> Any:
        return build_biohub_esmc_client(
            model_name=self._model_name,
            credential_handle=self._environment["credential_handle"],
            service_url=self._environment.get("service_url", "https://biohub.ai"),
        )

    def represent(
        self,
        sequence: ProteinSequence,
        *, outputs: str,
    ) -> ESMCSequenceRepresentation:
        """Return only the admitted provider-independent representation."""
        client = self._client()
        try:
            provider_protein = provider_sequence(sequence)
            with self._resources.engine_invocation(
                engine_role="sequence_encode",
            ) as encode_invocation_id:
                encoded = require_provider_success(
                    client.encode(provider_protein),
                    "encode",
                )
            config = logits_config(embedding=outputs in {"embedding", "both"}, logits=outputs in {"logits", "both"})
            with self._resources.engine_invocation(
                engine_role="sequence_logits",
                parent_invocation_id=encode_invocation_id,
            ):
                result = require_provider_success(
                    client.logits(encoded, config),
                    "logits",
                )
            return normalize_representation(
                sequence,
                result,
            )
        finally:
            client.close()
