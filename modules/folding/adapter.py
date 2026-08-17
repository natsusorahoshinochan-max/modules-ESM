"""Provider-native ESMFold2 decoding and static scientific normalization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, cast, Iterable, Protocol, TYPE_CHECKING

from core import ReadinessResult, RunResources
from modules.provider_contract import validate_installed_provider_checkout
from datatypes import ProteinSequence, ProteinStructure

from .esmfold2_contract import (
    ESM_SDK_REVISION,
    LOCAL_DEVICE,
    LOCAL_ESMC_ARTIFACT_SHA256,
    LOCAL_ESMC_MODEL,
    LOCAL_ESMC_PRECISION,
    LOCAL_ESMC_REVISION,
    LOCAL_ESMFOLD2_ARTIFACT_SHA256,
    LOCAL_ESMFOLD2_MODEL,
    LOCAL_ESMFOLD2_REVISION,
    LOCAL_TORCH_VERSION,
    REMOTE_ESMFOLD2_MODEL,
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


def remote_runtime_structurally_available() -> bool:
    return not (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("torch") is None
    )


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
        package_root = Path(
            distribution.locate_file("transformers")
        ).resolve(strict=True)
        for relative_path, expected_digest in (
            TRANSFORMERS_ESMFOLD2_SOURCE_SHA256.items()
        ):
            source = package_root / relative_path
            if _regular_file_sha256(source) != expected_digest:
                return False
    except (
        ImportError,
        importlib.metadata.PackageNotFoundError,
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        ValueError,
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


def remote_readiness(environment: object) -> bool:
    if not isinstance(environment, Mapping):
        return False
    client = environment.get("provider_client")
    factory = environment.get("client_factory")
    return (
        environment.get("endpoint_id") == "biohub"
        and environment.get("credential_handle") is not None
        and (
            callable(getattr(client, "fold", None))
            or callable(factory)
        )
        and _remote_provider_installation_is_exact()
    )


def _remote_provider_installation_is_exact() -> bool:
    if not remote_runtime_structurally_available():
        return False
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return True


@dataclass(frozen=True, slots=True)
class LocalESMFold2Runtime:
    """Local model paths admitted by the ESMFold2 Binding."""

    model_snapshot_path: Path
    language_model_snapshot_path: Path
    runtime_directory: Path
    device: str


def _local_input_builder(
    builder_type: type,
    runtime: LocalESMFold2Runtime,
) -> object:
    """Build the official input translator against the exact CCD snapshot."""
    return builder_type(ccd_cache=runtime.model_snapshot_path)


def _configured_directory(
    environment: Mapping[str, object],
    key: str,
) -> Path:
    raw = environment.get(key)
    if not isinstance(raw, (str, os.PathLike)):
        raise RuntimeError(f"local ESMFold2 {key} is not configured")
    try:
        path = Path(raw).resolve(strict=True)
    except OSError as error:
        raise RuntimeError(
            f"local ESMFold2 {key} is unavailable"
        ) from error
    if not path.is_dir():
        raise RuntimeError(
            f"local ESMFold2 {key} is not a directory"
        )
    return path


def _regular_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise RuntimeError(
            "local ESMFold2 artifact could not be validated"
        ) from error
    return digest.hexdigest()


def _artifact_source(
    snapshot_path: Path,
    relative_path: str,
    expected_digest: str,
) -> Path:
    try:
        target = (snapshot_path / relative_path).resolve(strict=True)
    except OSError as error:
        raise RuntimeError(
            "local ESMFold2 artifact could not be validated"
        ) from error
    if _regular_file_sha256(target) != expected_digest:
        raise RuntimeError("local ESMFold2 artifact identity mismatch")
    return target


def resolve_local_runtime(
    environment: Mapping[str, object],
) -> LocalESMFold2Runtime:
    """Resolve both immutable snapshots before any local model invocation."""
    if not local_runtime_structurally_available():
        raise RuntimeError("exact local ESMFold2 runtime is unavailable")
    validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    if not transformers_esmfold2_runtime_is_exact():
        raise RuntimeError("exact local ESMFold2 runtime is unavailable")
    import torch

    if str(torch.__version__) != LOCAL_TORCH_VERSION:
        raise RuntimeError("local ESMFold2 Torch runtime is not exact")
    if (
        environment.get("model_snapshot_revision")
        != LOCAL_ESMFOLD2_REVISION
        or environment.get("language_model_snapshot_revision")
        != LOCAL_ESMC_REVISION
    ):
        raise RuntimeError("local ESMFold2 snapshot revision is not exact")
    if environment.get("device") != LOCAL_DEVICE:
        raise RuntimeError("local ESMFold2 device does not match the Binding")
    model_path = _configured_directory(environment, "model_snapshot_path")
    language_path = _configured_directory(
        environment,
        "language_model_snapshot_path",
    )
    runtime_directory = _configured_directory(
        environment,
        "runtime_directory",
    )
    for relative_path, digest in LOCAL_ESMFOLD2_ARTIFACT_SHA256.items():
        _artifact_source(model_path, relative_path, digest)
    for relative_path, digest in LOCAL_ESMC_ARTIFACT_SHA256.items():
        _artifact_source(language_path, relative_path, digest)
    return LocalESMFold2Runtime(
        model_snapshot_path=model_path,
        language_model_snapshot_path=language_path,
        runtime_directory=runtime_directory,
        device=LOCAL_DEVICE,
    )


def _trusted_local_runtime(
    environment: Mapping[str, object],
) -> LocalESMFold2Runtime:
    """Read the runtime values already admitted by Binding readiness."""
    return LocalESMFold2Runtime(
        model_snapshot_path=Path(environment["model_snapshot_path"]),
        language_model_snapshot_path=Path(
            environment["language_model_snapshot_path"]
        ),
        runtime_directory=Path(environment["runtime_directory"]),
        device=LOCAL_DEVICE,
    )


def local_readiness(environment: object) -> ReadinessResult:
    """Return a bounded conclusion for exactly one selected local Binding."""
    if not isinstance(environment, Mapping):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    try:
        resolve_local_runtime(environment)
    except (ImportError, OSError, RuntimeError, ValueError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


@dataclass(frozen=True, slots=True)
class NormalizedConfidence:
    """Canonical confidence values for one complete structure Candidate."""

    per_residue_plddt: tuple[float | None, ...]
    ptm: float
    pae: tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class DecodedFoldResult:
    """Complete provider result ready for Candidate publication."""

    structure: ProteinStructure
    confidence: NormalizedConfidence


@dataclass(frozen=True, slots=True)
class ESMFold2AdapterResult:
    """Provider-independent result and actual effective call randomness."""

    structure: ProteinStructure
    confidence: NormalizedConfidence
    effective_call_seed: int | None


class ESMFold2Adapter(Protocol):
    """Canonical folding Operation boundary for one exact provider route."""

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult: ...


class _RenderedProtein(Protocol):
    def infer_oxygen(self) -> _RenderedProtein: ...

    def to_pdb_string(self) -> str: ...


class _RemoteFoldResult(Protocol):
    plddt: torch.Tensor
    ptm: torch.Tensor
    pae: torch.Tensor

    def to_protein_chain(self) -> _RenderedProtein: ...


class _LocalComplex(Protocol):
    sequence: Iterable[str]

    def to_protein_complex(self) -> _RenderedProtein: ...


class _LocalFoldResult(Protocol):
    complex: _LocalComplex
    plddt: torch.Tensor
    ptm: float
    pae: torch.Tensor


def _vector_values(value: torch.Tensor) -> tuple[float, ...]:
    return tuple(float(item) for item in value.detach().cpu().tolist())


def _matrix_values(value: torch.Tensor) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(float(item) for item in row)
        for row in value.detach().cpu().tolist()
    )


def _provider_pdb_string(protein: _RenderedProtein) -> str:
    rendered = protein.infer_oxygen().to_pdb_string()
    if not rendered.endswith("\n"):
        rendered = f"{rendered}\n"
    if rendered.splitlines()[-1][:6].strip() != "END":
        rendered = f"{rendered}END\n"
    return rendered


def decode_remote_fold_result(
    result: object,
    sequence: ProteinSequence,
) -> DecodedFoldResult:
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
    return DecodedFoldResult(
        ProteinStructure(pdb_string),
        confidence,
    )


def decode_local_fold_result(
    result: _LocalFoldResult,
) -> DecodedFoldResult:
    """Decode one provider-native local MolecularComplexResult."""
    tokens = result.complex.sequence
    mask = tuple(
        token.upper() in _PDB_RESIDUE_TO_ONE
        for token in tokens
    )
    pdb_string = _provider_pdb_string(result.complex.to_protein_complex())
    confidence = normalize_native_confidence(
        native_plddt=_vector_values(result.plddt),
        valid_protein_residues=mask,
        ptm=result.ptm,
        pae=_matrix_values(result.pae),
    )
    return DecodedFoldResult(
        ProteinStructure(pdb_string),
        confidence,
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


def remote_client(environment: Mapping[str, Any]) -> Any:
    client = environment.get("provider_client")
    if callable(getattr(client, "fold", None)):
        return client
    factory = environment.get("client_factory")
    if callable(factory):
        return factory(
            model_name=REMOTE_ESMFOLD2_MODEL,
            endpoint_id=environment["endpoint_id"],
            credential_handle=environment["credential_handle"],
        )
    raise RuntimeError("remote ESMFold2 client is unavailable")


def load_local_engine(
    environment: Mapping[str, Any],
    runtime: LocalESMFold2Runtime,
) -> Any:
    """Load the exact local snapshots only after Readiness has validated them."""
    client = environment.get("provider_client")
    if callable(getattr(client, "fold", None)):
        return client
    factory = environment.get("client_factory")
    if callable(factory):
        return factory(
            model_snapshot_path=runtime.model_snapshot_path,
            language_model_snapshot_path=(
                runtime.language_model_snapshot_path
            ),
            device=runtime.device,
            runtime_directory=runtime.runtime_directory,
        )

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
    builder = _local_input_builder(ESMFold2InputBuilder, runtime)

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


def normalize_residue_plddt(
    *,
    native_plddt: Iterable[object],
    valid_residues: Iterable[object],
    native_maximum: float,
    project_to_valid_residues: bool,
) -> tuple[tuple[float | None, ...], float, tuple[int, ...]]:
    """Normalize pLDDT while preserving the declared subject residue axis."""
    native = tuple(native_plddt)
    mask = tuple(valid_residues)
    selected_indices: list[int] = []
    canonical: list[float | None] = []
    for index, (value, valid) in enumerate(zip(native, mask, strict=True)):
        if project_to_valid_residues and not valid:
            continue
        selected_indices.append(index)
        if not valid:
            canonical.append(None)
            continue
        canonical.append(float(value) * (100.0 / native_maximum))
    finite_plddt = [value for value in canonical if value is not None]
    return (
        tuple(canonical),
        math.fsum(finite_plddt) / len(finite_plddt),
        tuple(selected_indices),
    )


def normalize_native_confidence(
    *,
    native_plddt: Iterable[object],
    valid_protein_residues: Iterable[object],
    ptm: float,
    pae: Iterable[Iterable[float]],
) -> NormalizedConfidence:
    """Convert exact native `[0,1]` ESMFold2 confidence without range guessing."""
    native = tuple(native_plddt)
    mask = tuple(valid_protein_residues)
    canonical, _, selected_indices = normalize_residue_plddt(
        native_plddt=native,
        valid_residues=mask,
        native_maximum=1.0,
        project_to_valid_residues=True,
    )

    ptm_value = float(ptm)
    pae_rows = tuple(tuple(row) for row in pae)
    normalized_pae: list[tuple[float, ...]] = []
    for row_index in selected_indices:
        row: list[float] = []
        for column_index in selected_indices:
            row.append(float(pae_rows[row_index][column_index]))
        normalized_pae.append(tuple(row))

    return NormalizedConfidence(
        per_residue_plddt=tuple(canonical),
        ptm=ptm_value,
        pae=tuple(normalized_pae),
    )


class BiohubESMFold2Adapter:
    """Translate one canonical sequence through the exact Biohub route."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._client: Any | None = None

    def _provider_client(self) -> Any:
        if self._client is None:
            self._client = remote_client(self._environment)
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
        provider_sequence = sequence.sequence
        client = self._provider_client()
        config = fixed_folding_config()
        with self._resources.engine_invocation(
            engine_role=engine_role,
            invocation_provenance={
                "effective_randomness": {
                    "control": "provider_uncontrolled",
                }
            },
        ):
            raw_result = client.fold(
                sequence=provider_sequence,
                model_name=REMOTE_ESMFOLD2_MODEL,
                config=config,
            )
        decoded = decode_remote_fold_result(raw_result, sequence)
        return ESMFold2AdapterResult(
            structure=decoded.structure,
            confidence=decoded.confidence,
            effective_call_seed=None,
        )


class LocalESMFold2Adapter:
    """Translate one canonical sequence through the exact local route."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
    ) -> None:
        self._environment = environment
        self._resources = resources
        self._runtime: LocalESMFold2Runtime | None = None
        self._engine: Any | None = None

    def _provider_engine(
        self,
    ) -> tuple[LocalESMFold2Runtime, Any]:
        if self._runtime is None:
            self._runtime = _trusted_local_runtime(self._environment)
        if self._engine is None:
            self._engine = load_local_engine(
                self._environment,
                self._runtime,
            )
        return self._runtime, self._engine

    def fold(
        self,
        *,
        sequence: ProteinSequence,
        derived_call_seed: int,
        engine_role: str,
    ) -> ESMFold2AdapterResult:
        """Invoke the local model once, then admit its raw result."""
        provider_sequence = sequence.sequence
        _, engine = self._provider_engine()
        with self._resources.engine_invocation(
            engine_role=engine_role,
            invocation_provenance={
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": derived_call_seed,
                }
            },
        ):
            raw_result = engine.fold(
                sequence=provider_sequence,
                effective_seed=derived_call_seed,
            )
        decoded = decode_local_fold_result(cast(_LocalFoldResult, raw_result))
        return ESMFold2AdapterResult(
            structure=decoded.structure,
            confidence=decoded.confidence,
            effective_call_seed=derived_call_seed,
        )
