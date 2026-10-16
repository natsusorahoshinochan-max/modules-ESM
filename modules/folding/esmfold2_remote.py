"""Biohub ESMFold2 provider translation."""

from __future__ import annotations

from collections.abc import Mapping
import importlib.util
from typing import Any, cast, Protocol, TYPE_CHECKING

from core.operation import (
    EngineInvocationProvenance,
    InvocationRandomness,
    OperationResources,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure

from .domain import (
    ESMFold2AdapterResult,
    _RenderedProtein,
    _matrix_values,
    _provider_pdb_string,
    _vector_values,
    normalize_native_confidence,
)
from .esmfold2_contract import (
    REMOTE_ESMFOLD2_MODEL,
)

if TYPE_CHECKING:
    import torch


class _RemoteFoldResult(Protocol):
    plddt: torch.Tensor
    ptm: torch.Tensor
    pae: torch.Tensor

    def to_protein_chain(self) -> _RenderedProtein: ...


def remote_runtime_structurally_available() -> bool:
    return not (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("esm.sdk") is None
        or importlib.util.find_spec("torch") is None
    )


def remote_readiness() -> bool:
    return remote_runtime_structurally_available()


def decode_remote_fold_result(
    result: object,
    sequence: ProteinSequence,
) -> ESMFold2AdapterResult:
    """Decode one provider-native Biohub ESMProtein result."""
    result = cast(_RemoteFoldResult, result)
    pdb_string = _provider_pdb_string(result.to_protein_chain())
    confidence = normalize_native_confidence(
        native_plddt=_vector_values(result.plddt),
        valid_protein_residues=(True,) * len(sequence.sequence),
        ptm=float(result.ptm.detach().cpu().item()),
        pae=_matrix_values(result.pae),
    )
    return ESMFold2AdapterResult(
        ProteinStructure(pdb_string),
        confidence,
        None,
    )


def folding_config(parameters: Mapping[str, Any]) -> Any:
    """Translate admitted inference controls, retaining required confidence output."""
    from esm.sdk.api import FoldingConfig

    return FoldingConfig(include_pae=True, include_embeddings=False, **parameters)


def build_remote_engine(environment: Mapping[str, Any]) -> Any:
    """Construct the official Biohub engine from admitted deployment values."""
    from esm.sdk import esmfold2_client

    return esmfold2_client(
        model=REMOTE_ESMFOLD2_MODEL,
        url=environment.get("service_url", "https://biohub.ai"),
        token=environment["credential_handle"],
        request_timeout=150,
    )


class ESMFold2ProviderError(RuntimeError):
    """The remote SDK reported an operational folding failure."""


class BiohubESMFold2Adapter:
    """Translate one canonical sequence through the exact Biohub route."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: OperationResources,
    ) -> None:
        self._environment = environment
        self._resources = resources

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        parameters: Mapping[str, Any],
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult:
        """Invoke Biohub once, then admit its raw result outside Invocation."""
        from esm.sdk.api import ESMProteinError

        del derived_call_seed
        engine = build_remote_engine(self._environment)
        try:
            config = folding_config(parameters)
            with self._resources.engine_invocation(
                engine_role=engine_role,
                invocation_provenance=EngineInvocationProvenance(
                    effective_randomness=InvocationRandomness(
                        control="provider_uncontrolled"
                    )
                ),
            ):
                try:
                    raw_result = engine.fold(
                        sequence=sequence.sequence,
                        model_name=REMOTE_ESMFOLD2_MODEL,
                        config=config,
                    )
                except ESMProteinError as error:
                    raise ESMFold2ProviderError(
                        "remote ESMFold2 provider request failed"
                    ) from error
                if isinstance(raw_result, ESMProteinError):
                    raise ESMFold2ProviderError(
                        "remote ESMFold2 provider returned an error"
                    )
            return decode_remote_fold_result(raw_result, sequence)
        finally:
            engine.close()
