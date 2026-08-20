"""Exact Protein Workbench adapter for Biohub ESMC sequence inference."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core import RunResources
from datatypes import ProteinSequence

from .domain import ESMCSequenceRepresentation


BIOHUB_ESMC_MODEL = "esmc-600m-2024-12"


def biohub_esmc_client_factory(
    *,
    model_name: str,
    endpoint_id: str,
    credential_handle: object,
) -> Any:
    """Construct the exact locked SDK client from trusted deployment values."""
    from esm.sdk import esmc_client

    return esmc_client(
        model=model_name,
        url={"biohub": "https://biohub.ai"}[endpoint_id],
        token=credential_handle,
    )


def provider_sequence(sequence: ProteinSequence) -> Any:
    """Translate one complete canonical sequence without changing its axis."""
    from esm.sdk.api import ESMProtein

    return ESMProtein(sequence=sequence.sequence)


def logits_config() -> Any:
    """Request the minimal scientific ESMC representation and real logits."""
    from esm.sdk.api import LogitsConfig

    return LogitsConfig(
        sequence=True,
        return_mean_embedding=True,
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
    """Translate locked-SDK tensors into the canonical value once."""
    logits_shape = tuple(result.logits.sequence.shape)
    mean_embedding = tuple(
        0.0 if float(value) == 0.0 else float(value)
        for value in result.mean_embedding[0, 0].detach().cpu().tolist()
    )
    return ESMCSequenceRepresentation(
        sequence=sequence.sequence,
        residue_ids=(
            None
            if sequence.residue_ids is None
            else tuple(sequence.residue_ids)
        ),
        mean_embedding=mean_embedding,
        sequence_logits_shape=logits_shape,
    )


def environment_ready(environment: object) -> bool:
    """Require an exact deployment client/factory and an opaque credential."""
    if not isinstance(environment, Mapping):
        return False
    if environment.get("endpoint_id") != "biohub":
        return False
    client = environment.get("provider_client")
    factory = environment.get("client_factory")
    return (
        (
            callable(getattr(client, "encode", None))
            and callable(getattr(client, "logits", None))
        )
        or callable(factory)
    ) and environment.get("credential_handle") is not None


class BiohubESMCAdapter:
    """Translate and admit the exact two-call Biohub ESMC operation."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
        model_name: str,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._model_name = model_name

    def _client(self) -> Any:
        client = self._environment.get("provider_client")
        if client is not None:
            return client
        return self._environment["client_factory"](
            model_name=self._model_name,
            endpoint_id=self._environment["endpoint_id"],
            credential_handle=self._environment["credential_handle"],
        )

    def represent(
        self,
        sequence: ProteinSequence,
    ) -> ESMCSequenceRepresentation:
        """Return only the admitted provider-independent representation."""
        client = self._client()
        provider_protein = provider_sequence(sequence)
        with self._resources.engine_invocation(
            engine_role="sequence_encode",
        ) as encode_invocation_id:
            encoded = require_provider_success(
                client.encode(provider_protein),
                "encode",
            )
        config = logits_config()
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
