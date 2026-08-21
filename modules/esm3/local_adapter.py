"""Exact local-open ESM-3 runtime validation, loading, and evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
from types import FunctionType
from typing import Any, cast
import weakref

from core import ReadinessResult, RunResources
from modules.provider_contract import (
    LOCAL_ESM3_SNAPSHOT_REVISION,
    LOCAL_ESM3_WEIGHT_SHA256,
    ProviderInstallationUnavailable,
    validate_installed_provider_checkout,
)

from .adapter import (
    ESM3Confidence,
    ESM_SDK_REVISION,
    _BaseESM3Adapter,
    require_provider_protein,
)


LOCAL_ESM3_MODEL = "esm3_sm_open_v1"
LOCAL_ESM3_SNAPSHOT_SOURCE = "biohub/esm3-sm-open-v1"
LOCAL_ESM3_DEVICE = "cpu"
LOCAL_ESM3_TORCH_VERSION = "2.13.0"
LOCAL_ESM3_PERFORMANCE_SETTINGS: Mapping[str, Any] = {}


class LocalESM3RuntimeUnavailable(RuntimeError):
    """The exact local ESM-3 runtime cannot be admitted."""


@dataclass(frozen=True, slots=True)
class LocalESM3Runtime:
    """Resolved paths admitted by the local ESM3 Binding."""

    snapshot_path: Path
    runtime_directory: Path
    device: str
    performance_settings: Mapping[str, Any]
    artifact_sources: Mapping[str, Path] = field(default_factory=dict)


def local_runtime_structurally_available() -> bool:
    """Check import prerequisites without loading model weights."""
    return not (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("torch") is None
    )


def _regular_file_sha256(path: Path) -> str:
    try:
        with path.open("rb") as artifact:
            return hashlib.file_digest(artifact, "sha256").hexdigest()
    except OSError as error:
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 model artifact could not be validated"
        ) from error


def _snapshot_artifact_source(
    snapshot_path: Path,
    relative_path: str,
    expected_digest: str,
) -> Path:
    target = snapshot_path / relative_path
    if _regular_file_sha256(target) != expected_digest:
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 model artifact identity mismatch"
        )
    return target


def _configured_path(environment: Mapping[str, Any], key: str) -> Path:
    value = environment.get(key)
    if not isinstance(value, (str, os.PathLike)):
        raise LocalESM3RuntimeUnavailable(
            f"local ESM-3 {key} is not configured"
        )
    try:
        path = Path(value).resolve(strict=True)
    except OSError as error:
        raise LocalESM3RuntimeUnavailable(
            f"local ESM-3 {key} is unavailable"
        ) from error
    if not path.is_dir():
        raise LocalESM3RuntimeUnavailable(
            f"local ESM-3 {key} is not a directory"
        )
    return path


def _validated_performance_settings(
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    raw = environment.get("performance_settings", {})
    if not isinstance(raw, Mapping) or dict(raw) != dict(
        LOCAL_ESM3_PERFORMANCE_SETTINGS
    ):
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 performance settings do not match the Binding"
        )
    return dict(LOCAL_ESM3_PERFORMANCE_SETTINGS)


def _validate_device(device: object) -> str:
    if device != LOCAL_ESM3_DEVICE:
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 device does not match the Binding"
        )
    try:
        import torch
    except ImportError as error:
        raise LocalESM3RuntimeUnavailable(
            "exact local ESM-3 runtime is unavailable"
        ) from error

    if str(torch.__version__) != LOCAL_ESM3_TORCH_VERSION:
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 Torch runtime does not match the Binding"
        )
    return LOCAL_ESM3_DEVICE


def resolve_local_runtime(
    environment: Mapping[str, Any],
) -> LocalESM3Runtime:
    """Validate exact artifacts before entering the local Provider."""
    if not local_runtime_structurally_available():
        raise LocalESM3RuntimeUnavailable(
            "exact local ESM-3 runtime is unavailable"
        )
    validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    if (
        environment.get("model_snapshot_revision")
        != LOCAL_ESM3_SNAPSHOT_REVISION
    ):
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 snapshot revision is not exact"
        )
    snapshot_path = _configured_path(environment, "model_snapshot_path")
    runtime_directory = _configured_path(environment, "runtime_directory")
    device = _validate_device(environment.get("device"))
    performance_settings = _validated_performance_settings(environment)
    artifact_sources: dict[str, Path] = {}
    for relative_path, expected_digest in LOCAL_ESM3_WEIGHT_SHA256.items():
        artifact_sources[relative_path] = _snapshot_artifact_source(
            snapshot_path,
            relative_path,
            expected_digest,
        )
    return LocalESM3Runtime(
        snapshot_path=snapshot_path,
        runtime_directory=runtime_directory,
        device=device,
        performance_settings=performance_settings,
        artifact_sources=artifact_sources,
    )


def _trusted_local_runtime(
    environment: Mapping[str, Any],
) -> LocalESM3Runtime:
    """Read runtime facts already admitted by per-run Binding readiness."""
    snapshot_path = Path(environment["model_snapshot_path"])
    return LocalESM3Runtime(
        snapshot_path=snapshot_path,
        runtime_directory=Path(environment["runtime_directory"]),
        device=LOCAL_ESM3_DEVICE,
        performance_settings=dict(LOCAL_ESM3_PERFORMANCE_SETTINGS),
        artifact_sources={
            relative_path: snapshot_path / relative_path
            for relative_path in LOCAL_ESM3_WEIGHT_SHA256
        },
    )


def local_readiness(environment: Mapping[str, Any]) -> ReadinessResult:
    """Return one bounded, redacted conclusion for the selected local Binding."""
    try:
        resolve_local_runtime(environment)
    except (
        LocalESM3RuntimeUnavailable,
        ProviderInstallationUnavailable,
    ):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def stage_local_runtime(runtime: LocalESM3Runtime) -> Path:
    """Stage the model artifacts already admitted by Binding readiness."""
    staged_root = Path(
        tempfile.mkdtemp(
            prefix="esm3-sm-open-v1-",
            dir=runtime.runtime_directory,
        )
    )
    staged_root.chmod(0o700)
    try:
        for relative_path in LOCAL_ESM3_WEIGHT_SHA256:
            source = runtime.artifact_sources[relative_path]
            destination = staged_root / relative_path
            destination.parent.mkdir(
                mode=0o700,
                parents=True,
                exist_ok=True,
            )
            shutil.copyfile(source, destination)
        return staged_root
    except BaseException:
        shutil.rmtree(staged_root)
        raise


def _bind_builder_to_staged_root(
    builder: FunctionType,
    staged_root: Path,
) -> FunctionType:
    """Clone an SDK builder with a private data-root binding."""
    builder_globals = dict(builder.__globals__)
    builder_globals["data_root"] = lambda model: staged_root
    bound = FunctionType(
        builder.__code__,
        builder_globals,
        builder.__name__,
        builder.__defaults__,
        builder.__closure__,
    )
    bound.__kwdefaults__ = builder.__kwdefaults__
    return bound


def load_local_esm3_client(
    environment: Mapping[str, Any],
    *,
    model_name: str,
    runtime: LocalESM3Runtime | None = None,
) -> Any:
    """Load only the exact readiness-validated local model on explicit demand."""
    if runtime is None:
        runtime = resolve_local_runtime(environment)
    import torch
    import esm.pretrained as esm_pretrained

    staged_root = stage_local_runtime(runtime)
    try:
        builders = esm_pretrained.LOCAL_MODEL_REGISTRY
        required_builders: dict[str, FunctionType] = {
            name: cast(FunctionType, builders[name])
            for name in (
                model_name,
                "esm3_structure_encoder_v0",
                "esm3_structure_decoder_v0",
                "esm3_function_decoder_v0",
            )
        }
        bound = {
            name: _bind_builder_to_staged_root(builder, staged_root)
            for name, builder in required_builders.items()
        }
        client = bound[model_name](torch.device(runtime.device))
        client.structure_encoder_fn = bound["esm3_structure_encoder_v0"]
        client.structure_decoder_fn = bound["esm3_structure_decoder_v0"]
        client.function_decoder_fn = bound["esm3_function_decoder_v0"]
        client = client.float()
        client._protein_workbench_staged_root = staged_root
        client._protein_workbench_staged_cleanup = weakref.finalize(
            client,
            shutil.rmtree,
            staged_root,
        )
        return client
    except BaseException:
        shutil.rmtree(staged_root)
        raise


def release_local_esm3_client(client: Any) -> None:
    """Release private staged weights owned by an internally loaded client."""
    cleanup = getattr(client, "_protein_workbench_staged_cleanup", None)
    staged_root = getattr(client, "_protein_workbench_staged_root", None)
    if isinstance(staged_root, Path) and staged_root.exists():
        shutil.rmtree(staged_root)
    if cleanup is not None and bool(getattr(cleanup, "alive", False)):
        cleanup.detach()


def call_local_provider(
    client: Any,
    protein: Any,
    config: Any,
    operation: str,
    *,
    effective_seed: int,
) -> Any:
    """Execute one local call under the exact derived Torch seed."""
    import torch
    from esm.sdk.api import ESMProteinError

    try:
        with torch.random.fork_rng():
            torch.manual_seed(effective_seed)
            result = client.generate(protein, config)
    except ESMProteinError as error:
        raise RuntimeError(
            f"local ESM-3 provider operation {operation} failed"
        ) from error
    return require_provider_protein(result, operation)


class LocalESM3Adapter(_BaseESM3Adapter):
    """Translate canonical ESM-3 calls to the pinned local-open runtime."""

    def __init__(
        self,
        *,
        environment: Mapping[str, Any],
        resources: RunResources,
        model_name: str,
    ) -> None:
        super().__init__(
            resources=resources,
            model_name=model_name,
            exact_seed_control=True,
        )
        self._environment = environment
        self._resolved_client: Any | None = None
        self._owned_local_client: Any | None = None

    def _client(self) -> Any:
        if self._resolved_client is not None:
            return self._resolved_client
        runtime = _trusted_local_runtime(self._environment)
        client = self._environment.get("provider_client")
        if client is not None:
            self._resolved_client = client
            return client
        client_factory = self._environment.get("client_factory")
        if client_factory is not None:
            client = client_factory(
                model_name=self._model_name,
                model_snapshot_path=runtime.snapshot_path,
                device=runtime.device,
                runtime_directory=runtime.runtime_directory,
                performance_settings=dict(runtime.performance_settings),
            )
            self._resolved_client = client
            return client
        client = load_local_esm3_client(
            self._environment,
            model_name=self._model_name,
            runtime=runtime,
        )
        self._owned_local_client = client
        self._resolved_client = client
        return client

    def _call_provider(
        self,
        client: Any,
        provider_prompt: Any,
        config: Any,
        provider_operation: str,
        *,
        effective_call_seed: int | None,
    ) -> Any:
        return call_local_provider(
            client,
            provider_prompt,
            config,
            provider_operation,
            effective_seed=cast(int, effective_call_seed),
        )

    def _admit_confidence(self, result: Any) -> ESM3Confidence:
        """Translate pinned local decoder tensors after BOS/EOS removal."""
        ptm = float(result.ptm[0].detach().cpu().item())
        plddt = tuple(
            float(value) * 100.0
            for value in result.plddt.detach().cpu().tolist()
        )
        pae = (
            None
            if result.pae is None
            else tuple(
                tuple(float(value) for value in row)
                for row in result.pae[0, 1:-1, 1:-1]
                .detach()
                .cpu()
                .tolist()
            )
        )
        return ESM3Confidence(
            ptm=ptm,
            plddt_per_residue=plddt,
            pae=pae,
        )

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> None:
        del exception_type, traceback
        client = self._owned_local_client
        self._owned_local_client = None
        self._resolved_client = None
        if client is None:
            return
        try:
            release_local_esm3_client(client)
        except BaseException as cleanup_error:
            if not isinstance(exception, BaseException):
                raise
            exception.add_note(
                "Local ESM-3 staged-weight cleanup also failed: "
                f"{type(cleanup_error).__name__}"
            )
