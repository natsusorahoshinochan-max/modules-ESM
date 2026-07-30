"""Exact Protein Workbench adapter for Biohub ESMC sequence inference."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from datatypes import ProteinSequence

from .domain import ESMCSequenceRepresentation


BIOHUB_ESMC_MODEL = "esmc-600m-2024-12"
BIOHUB_ESMC_EMBEDDING_DIMENSION = 1152
BIOHUB_ESMC_LOGITS_DIMENSION = 64


def biohub_esmc_client_factory(
    *,
    model_name: str,
    endpoint_id: str,
    credential_handle: object,
) -> Any:
    """Construct the exact locked SDK client from trusted deployment values."""
    if model_name != BIOHUB_ESMC_MODEL or endpoint_id != "biohub":
        raise ValueError("Biohub ESMC client identity is not exact")
    if not isinstance(credential_handle, str) or not credential_handle:
        raise ValueError("Biohub ESMC requires a non-empty credential handle")
    from esm.sdk import esmc_client

    return esmc_client(
        model=model_name,
        url="https://biohub.ai",
        token=credential_handle,
    )


def provider_sequence(sequence: ProteinSequence) -> Any:
    """Translate one complete canonical sequence without changing its axis."""
    if type(sequence) is not ProteinSequence:
        raise ValueError("direct ESMC inference requires one ProteinSequence")
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


def _tensor_shape(value: object, field: str) -> tuple[int, ...]:
    try:
        shape = tuple(int(dimension) for dimension in value.shape)  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"Biohub ESMC {field} is not a tensor") from error
    if not shape or any(dimension <= 0 for dimension in shape):
        raise ValueError(f"Biohub ESMC {field} has an invalid shape")
    return shape


def _finite_binary32_vector(value: object, field: str) -> tuple[float, ...]:
    import torch

    try:
        tensor = value.detach().to(dtype=torch.float32).cpu()  # type: ignore[union-attr]
        shape = tuple(int(dimension) for dimension in tensor.shape)
        while len(shape) > 1 and shape[0] == 1:
            tensor = tensor[0]
            shape = tuple(int(dimension) for dimension in tensor.shape)
        if len(shape) != 1 or shape[0] <= 0:
            raise ValueError
        result = tuple(
            0.0 if float(item) == 0.0 else float(item)
            for item in tensor.tolist()
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(
            f"Biohub ESMC {field} is not one binary32 vector"
        ) from error
    if any(not math.isfinite(item) for item in result):
        raise ValueError(f"Biohub ESMC {field} contains non-finite values")
    return result


def normalize_representation(
    sequence: ProteinSequence,
    result: object,
    *,
    model_name: str,
) -> ESMCSequenceRepresentation:
    """Validate the two requested scientific outputs and publish one value."""
    if model_name != BIOHUB_ESMC_MODEL:
        raise ValueError("Biohub ESMC result model identity is not exact")
    logits = getattr(getattr(result, "logits", None), "sequence", None)
    logits_shape = _tensor_shape(logits, "sequence logits")
    if (
        len(logits_shape) == 3
        and logits_shape[0] != 1
    ) or len(logits_shape) not in {2, 3}:
        raise ValueError(
            "Biohub ESMC sequence logits must describe one sequence batch"
        )
    token_axis = logits_shape[-2]
    if token_axis != len(sequence.sequence) + 2:
        raise ValueError(
            "Biohub ESMC sequence logits do not match the encoded sequence axis"
        )
    if logits_shape[-1] != BIOHUB_ESMC_LOGITS_DIMENSION:
        raise ValueError(
            "Biohub ESMC sequence logits dimension does not match the exact "
            "model contract"
        )
    mean_embedding = _finite_binary32_vector(
        getattr(result, "mean_embedding", None),
        "mean embedding",
    )
    if len(mean_embedding) != BIOHUB_ESMC_EMBEDDING_DIMENSION:
        raise ValueError(
            "Biohub ESMC mean embedding dimension does not match the exact "
            "model contract"
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
