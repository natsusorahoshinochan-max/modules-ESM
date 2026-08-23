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
from core.provider_support import (
    ProviderInstallationUnavailable,
    validate_installed_provider_checkout,
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
    ESM_SDK_REVISION,
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
        or importlib.util.find_spec("torch") is None
    )


def remote_readiness(environment: Mapping[str, Any]) -> bool:
    return (
        environment["endpoint_id"] == "biohub"
        and _remote_provider_installation_is_exact()
    )


def _remote_provider_installation_is_exact() -> bool:
    if not remote_runtime_structurally_available():
        return False
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    except ProviderInstallationUnavailable:
        return False
    return True


def decode_remote_fold_result(
    result: object,
    sequence: ProteinSequence,
) -> ESMFold2AdapterResult:
    """Decode one provider-native Biohub ESMProtein result."""
    from esm.sdk.api import ESMProteinError

    if isinstance(result, ESMProteinError):
        raise RuntimeError("remote ESMFold2 provider returned an error")
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


def fixed_folding_config() -> Any:
    """Build the Method-fixed remote configuration with complete confidence."""
    from esm.sdk.api import FoldingConfig

    return FoldingConfig(
        include_pae=True,
        include_embeddings=False,
        num_sampling_steps=100,
        num_loops=20,
        lm_dropout=0.3,
        lm_mask_pct=0.1,
        msa_max_depth=1024,
        msa_column_mask_rate=0.1,
    )


def build_remote_engine(environment: Mapping[str, Any]) -> Any:
    """Construct the official Biohub engine from admitted deployment values."""
    from esm.sdk import esmfold2_client

    return esmfold2_client(
        model=REMOTE_ESMFOLD2_MODEL,
        url={"biohub": "https://biohub.ai"}[environment["endpoint_id"]],
        token=environment["credential_handle"],
    )


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
        self._client: Any | None = None

    def _engine(self) -> Any:
        if self._client is None:
            self._client = build_remote_engine(self._environment)
        return self._client

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult:
        """Invoke Biohub once, then admit its raw result outside Invocation."""
        del derived_call_seed
        with self._resources.engine_invocation(
            engine_role=engine_role,
            invocation_provenance=EngineInvocationProvenance(
                effective_randomness=InvocationRandomness(
                    control="provider_uncontrolled"
                )
            ),
        ):
            raw_result = self._engine().fold(
                sequence=sequence.sequence,
                model_name=REMOTE_ESMFOLD2_MODEL,
                config=fixed_folding_config(),
            )
        return decode_remote_fold_result(raw_result, sequence)
