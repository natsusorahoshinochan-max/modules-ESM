"""Pinned local ESMFold2 provider translation and lifecycle."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
from typing import Any, cast, Protocol, TYPE_CHECKING

from core.operation import (
    EngineInvocationProvenance,
    InvocationRandomness,
    OperationResources,
    ReadinessResult,
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
    LOCAL_DEVICE,
    LOCAL_ESMC_ARTIFACT_SHA256,
    LOCAL_ESMC_PRECISION,
    LOCAL_ESMC_REVISION,
    LOCAL_ESMFOLD2_ARTIFACT_SHA256,
    LOCAL_ESMFOLD2_REVISION,
    LOCAL_TORCH_VERSION,
    TRANSFORMERS_ESMFOLD2_SOURCE_SHA256,
    TRANSFORMERS_REVISION,
)

if TYPE_CHECKING:
    import torch


_PDB_RESIDUE_TO_ONE = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


class LocalESMFold2RuntimeUnavailable(RuntimeError):
    """The exact local ESMFold2 runtime cannot be admitted."""


@dataclass(frozen=True, slots=True)
class LocalESMFold2Runtime:
    """Local model paths admitted by the ESMFold2 Binding."""

    model_snapshot_path: Path
    language_model_snapshot_path: Path
    device: str


class _LocalComplex(Protocol):
    sequence: Iterable[str]

    def to_protein_complex(self) -> _RenderedProtein: ...


class _LocalFoldResult(Protocol):
    complex: _LocalComplex
    plddt: torch.Tensor
    ptm: float
    pae: torch.Tensor


def transformers_esmfold2_runtime_is_exact() -> bool:
    """Verify the installed ESMFold2 source files against one reviewed commit."""
    try:
        distribution = importlib.metadata.distribution("transformers")
        direct_url_text = distribution.read_text("direct_url.json")
        if not direct_url_text:
            return False
        direct_url = json.loads(direct_url_text)
        vcs_info = direct_url.get("vcs_info")
        if (
            direct_url.get("url")
            != "https://github.com/Biohub/transformers.git"
            or not isinstance(vcs_info, dict)
            or vcs_info.get("vcs") != "git"
            or vcs_info.get("commit_id") != TRANSFORMERS_REVISION
        ):
            return False
        package_root = Path(distribution.locate_file("transformers"))
        for relative_path, expected_digest in (
            TRANSFORMERS_ESMFOLD2_SOURCE_SHA256.items()
        ):
            source = package_root / relative_path
            if _regular_file_sha256(source) != expected_digest:
                return False
    except (
        importlib.metadata.PackageNotFoundError,
        json.JSONDecodeError,
        LocalESMFold2RuntimeUnavailable,
        OSError,
    ):
        return False
    return True


def local_runtime_structurally_available() -> bool:
    return not (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("torch") is None
        or importlib.util.find_spec("transformers") is None
        or importlib.util.find_spec(
            "transformers.models.esmfold2.modeling_esmfold2"
        )
        is None
    )


def _regular_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise LocalESMFold2RuntimeUnavailable(
            "local ESMFold2 artifact could not be validated"
        ) from error
    return digest.hexdigest()


def _artifact_source(
    snapshot_path: Path,
    relative_path: str,
    expected_digest: str,
) -> None:
    target = snapshot_path / relative_path
    if _regular_file_sha256(target) != expected_digest:
        raise LocalESMFold2RuntimeUnavailable(
            "local ESMFold2 artifact identity mismatch"
        )


def resolve_local_runtime(
    environment: Mapping[str, object],
) -> LocalESMFold2Runtime:
    """Resolve both immutable snapshots before any local model invocation."""
    validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    if not transformers_esmfold2_runtime_is_exact():
        raise LocalESMFold2RuntimeUnavailable(
            "exact local ESMFold2 runtime is unavailable"
        )
    import torch

    if str(torch.__version__) != LOCAL_TORCH_VERSION:
        raise LocalESMFold2RuntimeUnavailable(
            "local ESMFold2 Torch runtime is not exact"
        )
    if (
        environment["model_snapshot_revision"]
        != LOCAL_ESMFOLD2_REVISION
        or environment["language_model_snapshot_revision"]
        != LOCAL_ESMC_REVISION
    ):
        raise LocalESMFold2RuntimeUnavailable(
            "local ESMFold2 snapshot revision is not exact"
        )
    if environment["device"] != LOCAL_DEVICE:
        raise LocalESMFold2RuntimeUnavailable(
            "local ESMFold2 device does not match the Binding"
        )
    model_path = cast(Path, environment["model_snapshot_path"])
    language_path = cast(Path, environment["language_model_snapshot_path"])
    for relative_path, digest in LOCAL_ESMFOLD2_ARTIFACT_SHA256.items():
        _artifact_source(model_path, relative_path, digest)
    for relative_path, digest in LOCAL_ESMC_ARTIFACT_SHA256.items():
        _artifact_source(language_path, relative_path, digest)
    return LocalESMFold2Runtime(
        model_snapshot_path=model_path,
        language_model_snapshot_path=language_path,
        device=LOCAL_DEVICE,
    )


def _trusted_local_runtime(
    environment: Mapping[str, object],
) -> LocalESMFold2Runtime:
    """Read the runtime values already admitted by Binding readiness."""
    return LocalESMFold2Runtime(
        model_snapshot_path=cast(Path, environment["model_snapshot_path"]),
        language_model_snapshot_path=cast(
            Path,
            environment["language_model_snapshot_path"],
        ),
        device=LOCAL_DEVICE,
    )


def local_readiness(environment: Mapping[str, Any]) -> ReadinessResult:
    """Return a bounded conclusion for exactly one selected local Binding."""
    try:
        resolve_local_runtime(environment)
    except (
        LocalESMFold2RuntimeUnavailable,
        ProviderInstallationUnavailable,
    ):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def decode_local_fold_result(
    result: _LocalFoldResult,
    *,
    effective_call_seed: int | None = None,
) -> ESMFold2AdapterResult:
    """Decode one provider-native local MolecularComplexResult."""
    mask = tuple(
        token.upper() in _PDB_RESIDUE_TO_ONE
        for token in result.complex.sequence
    )
    pdb_string = _provider_pdb_string(result.complex.to_protein_complex())
    confidence = normalize_native_confidence(
        native_plddt=_vector_values(result.plddt),
        valid_protein_residues=mask,
        ptm=result.ptm,
        pae=_matrix_values(result.pae),
    )
    return ESMFold2AdapterResult(
        ProteinStructure(pdb_string),
        confidence,
        effective_call_seed,
    )


def load_local_engine(runtime: LocalESMFold2Runtime) -> Any:
    """Load the exact local snapshots already admitted by Readiness."""
    from esm.models.esmfold2 import (
        ESMFold2InputBuilder,
        ProteinInput,
        StructurePredictionInput,
    )
    from transformers.models.esmfold2.configuration_esmfold2 import (
        ESMFold2Config,
    )
    from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model

    configuration = ESMFold2Config.from_pretrained(
        runtime.model_snapshot_path,
        local_files_only=True,
    )
    configuration.esmc_id = str(runtime.language_model_snapshot_path)
    model = ESMFold2Model.from_pretrained(
        runtime.model_snapshot_path,
        config=configuration,
        local_files_only=True,
        esmc_precision=LOCAL_ESMC_PRECISION,
    ).to(runtime.device).eval()
    builder = ESMFold2InputBuilder(ccd_cache=runtime.model_snapshot_path)

    class LocalEngine:
        def fold(
            self,
            *,
            sequence: str,
            effective_seed: int,
        ) -> object:
            provider_input = StructurePredictionInput(
                sequences=[ProteinInput(id="A", sequence=sequence)]
            )
            return builder.fold(
                model,
                provider_input,
                num_loops=20,
                num_sampling_steps=100,
                num_diffusion_samples=1,
                seed=effective_seed,
                lm_dropout=0.3,
                lm_mask_pct=0.1,
                msa_max_depth=1024,
                msa_column_mask_rate=0.1,
                complex_id="protein-workbench-fold",
            )

    return LocalEngine()


class LocalESMFold2Adapter:
    """Translate one canonical sequence through the exact local route."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: OperationResources,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._runtime: LocalESMFold2Runtime | None = None
        self._engine: Any | None = None

    def _provider_engine(self) -> Any:
        if self._runtime is None:
            self._runtime = _trusted_local_runtime(self._environment)
        if self._engine is None:
            self._engine = load_local_engine(self._runtime)
        return self._engine

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult:
        """Invoke the local model once, then admit its raw result."""
        with self._resources.engine_invocation(
            engine_role=engine_role,
            invocation_provenance=EngineInvocationProvenance(
                effective_randomness=InvocationRandomness(
                    control="exact_seed",
                    effective_seed=derived_call_seed,
                )
            ),
        ):
            raw_result = self._provider_engine().fold(
                sequence=sequence.sequence,
                effective_seed=derived_call_seed,
            )
        return decode_local_fold_result(
            cast(_LocalFoldResult, raw_result),
            effective_call_seed=derived_call_seed,
        )
