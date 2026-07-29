"""Exact local-open ESM-3 runtime validation, loading, and evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import threading
from typing import Any

from core import ReadinessResult, canonical_sha256
from core.provider_contract import validate_installed_provider_checkout

from .adapter import ESM_SDK_REVISION, require_provider_protein


LOCAL_ESM3_MODEL = "esm3_sm_open_v1"
LOCAL_ESM3_SNAPSHOT_SOURCE = "biohub/esm3-sm-open-v1"
LOCAL_ESM3_SNAPSHOT_REVISION = (
    "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
)
LOCAL_ESM3_WEIGHT_SHA256 = {
    "data/weights/esm3_sm_open_v1.pth": (
        "5ead5a135c658068db6a4f1b933e72d6110992c4668822e1c0e2dcc53e38acd9"
    ),
    "data/weights/esm3_structure_encoder_v0.pth": (
        "467acbaee703ba3ccde6e75241a912a316952e5ff071355f85c1d33c68704f40"
    ),
    "data/weights/esm3_structure_decoder_v0.pth": (
        "3b726258a44274792b40ce7ea307e10c5da09936368a4ffa2970264d909da65b"
    ),
    "data/weights/esm3_function_decoder_v0.pth": (
        "f76d074efcaccfe21365a4fa96f212dadd66798e1e49d809ab7ffbe025d227c9"
    ),
}
_PERFORMANCE_KEYS = frozenset(
    {"torch_num_threads", "float32_matmul_precision"}
)
_MODEL_LOAD_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class LocalESM3Runtime:
    """Resolved private paths paired with one safe runtime identity."""

    snapshot_path: Path
    runtime_directory: Path
    device: str
    performance_settings: Mapping[str, Any]
    safe_fingerprint: str


def local_runtime_structurally_available() -> bool:
    """Check import/source prerequisites without loading model weights."""
    if (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("torch") is None
    ):
        return False
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return True


def _snapshot_file_sha256(snapshot_path: Path, relative_path: str) -> str:
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuntimeError("local ESM-3 model artifact path is invalid")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        directory_descriptor = os.open(snapshot_path, directory_flags)
        for component in relative.parts[:-1]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        file_descriptor = os.open(
            relative.parts[-1],
            file_flags,
            dir_fd=directory_descriptor,
        )
        opened = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeError(
                "required local ESM-3 model artifact is not regular"
            )
        digest = hashlib.sha256()
        while chunk := os.read(file_descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(file_descriptor)
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ):
            raise RuntimeError("local ESM-3 model artifact changed during validation")
        return digest.hexdigest()
    except OSError as error:
        raise RuntimeError("local ESM-3 model artifact could not be validated") from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _configured_path(environment: Mapping[str, Any], key: str) -> Path:
    value = environment.get(key)
    if not isinstance(value, (str, os.PathLike)):
        raise RuntimeError(f"local ESM-3 {key} is not configured")
    path = Path(value)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise RuntimeError(f"local ESM-3 {key} is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"local ESM-3 {key} is not a regular directory")
    return path.resolve(strict=True)


def _validated_performance_settings(
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    raw = environment.get("performance_settings", {})
    if not isinstance(raw, Mapping) or not set(raw).issubset(_PERFORMANCE_KEYS):
        raise RuntimeError("local ESM-3 performance settings are invalid")
    settings = dict(raw)
    threads = settings.get("torch_num_threads")
    if threads is not None and (type(threads) is not int or threads < 1):
        raise RuntimeError("local ESM-3 torch thread count is invalid")
    precision = settings.get("float32_matmul_precision")
    if precision is not None and precision not in {"highest", "high", "medium"}:
        raise RuntimeError("local ESM-3 matmul precision is invalid")
    return settings


def _validate_device(device: object) -> tuple[str, str]:
    if device not in {"cpu", "cuda", "mps"}:
        raise RuntimeError("local ESM-3 device is invalid")
    import torch

    available = (
        device == "cpu"
        or (device == "cuda" and torch.cuda.is_available())
        or (
            device == "mps"
            and bool(
                getattr(
                    getattr(torch.backends, "mps", None),
                    "is_available",
                    lambda: False,
                )()
            )
        )
    )
    if not available:
        raise RuntimeError("configured local ESM-3 device is unavailable")
    return str(device), str(torch.__version__)


def _runtime_fingerprint(
    *,
    device: str,
    torch_version: str,
    performance_settings: Mapping[str, Any],
) -> str:
    return canonical_sha256(
        {
            "schema_namespace": "protein-workbench-local-esm3-runtime/v2",
            "model": LOCAL_ESM3_MODEL,
            "snapshot_source": LOCAL_ESM3_SNAPSHOT_SOURCE,
            "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
            "weight_sha256": dict(sorted(LOCAL_ESM3_WEIGHT_SHA256.items())),
            "sdk_source_revision": ESM_SDK_REVISION,
            "device": device,
            "torch_version": torch_version,
            "performance_settings": dict(sorted(performance_settings.items())),
            "runtime_directory_policy": "binding-scoped-private",
        }
    )


def resolve_local_runtime(
    environment: Mapping[str, Any],
) -> LocalESM3Runtime:
    """Validate exact artifacts and safe configuration before any Cache lookup."""
    if not local_runtime_structurally_available():
        raise RuntimeError("exact local ESM-3 runtime is unavailable")
    if (
        environment.get("model_snapshot_revision")
        != LOCAL_ESM3_SNAPSHOT_REVISION
    ):
        raise RuntimeError("local ESM-3 snapshot revision is not exact")
    snapshot_path = _configured_path(environment, "model_snapshot_path")
    runtime_directory = _configured_path(environment, "runtime_directory")
    for relative_path, expected_digest in LOCAL_ESM3_WEIGHT_SHA256.items():
        if _snapshot_file_sha256(snapshot_path, relative_path) != expected_digest:
            raise RuntimeError("local ESM-3 model artifact identity mismatch")
    device, torch_version = _validate_device(environment.get("device"))
    performance_settings = _validated_performance_settings(environment)
    safe_fingerprint = _runtime_fingerprint(
        device=device,
        torch_version=torch_version,
        performance_settings=performance_settings,
    )
    if environment.get("resolved_runtime_fingerprint") != safe_fingerprint:
        raise RuntimeError("local ESM-3 runtime fingerprint is stale")
    return LocalESM3Runtime(
        snapshot_path=snapshot_path,
        runtime_directory=runtime_directory,
        device=device,
        performance_settings=performance_settings,
        safe_fingerprint=safe_fingerprint,
    )


def local_readiness(environment: Mapping[str, Any]) -> ReadinessResult:
    """Return one bounded, redacted conclusion for the selected local Binding."""
    try:
        resolve_local_runtime(environment)
    except (ImportError, OSError, RuntimeError, ValueError):
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def load_local_esm3_client(
    environment: Mapping[str, Any],
    *,
    model_name: str,
) -> Any:
    """Load only the exact readiness-validated local model on explicit demand."""
    if model_name != LOCAL_ESM3_MODEL:
        raise RuntimeError("local ESM-3 Binding requested an unknown model")
    runtime = resolve_local_runtime(environment)
    import torch
    from esm.models.esm3 import ESM3
    import esm.pretrained as esm_pretrained

    threads = runtime.performance_settings.get("torch_num_threads")
    if threads is not None:
        torch.set_num_threads(threads)
    precision = runtime.performance_settings.get("float32_matmul_precision")
    if precision is not None:
        torch.set_float32_matmul_precision(precision)
    with _MODEL_LOAD_LOCK:
        original_data_root = esm_pretrained.data_root
        esm_pretrained.data_root = lambda model: runtime.snapshot_path
        try:
            client = ESM3.from_pretrained(
                model_name,
                device=torch.device(runtime.device),
            )
        finally:
            esm_pretrained.data_root = original_data_root
    return client.float() if runtime.device == "cpu" else client


def _track_identity(protein: Any) -> dict[str, Any]:
    secondary_structure = getattr(protein, "secondary_structure", None)
    if not isinstance(secondary_structure, str):
        return {}
    return {
        "secondary_structure_length": len(secondary_structure),
        "secondary_structure_sha256": hashlib.sha256(
            secondary_structure.encode()
        ).hexdigest(),
    }


def prepare_local_provider_call(
    protein: Any,
    operation: str,
    *,
    model_name: str,
    effective_seed: int,
    runtime_fingerprint: str,
) -> dict[str, Any]:
    """Record exact local call intent before entering the model seam."""
    from core.run_context import RunContext

    track_identity = _track_identity(protein)
    RunContext.record_active_provider_call(
        "local_open",
        operation,
        model=model_name,
        details={
            **track_identity,
            "runtime_fingerprint": runtime_fingerprint,
            "effective_seed": effective_seed,
        },
    )
    return track_identity


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


def record_local_provider_result(
    protein: Any,
    result: Any,
    operation: str,
    *,
    model_name: str,
    effective_seed: int,
    track_identity: Mapping[str, Any],
    runtime_fingerprint: str,
) -> None:
    """Persist safe local provider identity after the Engine Invocation."""
    from core.provider_evidence import record_provider_call_result

    result_summary: dict[str, Any] = {
        "result_type": type(result).__name__,
        "has_sequence": getattr(result, "sequence", None) is not None,
        "has_coordinates": getattr(result, "coordinates", None) is not None,
        **track_identity,
    }
    for prefix, value in (
        ("input", getattr(protein, "sequence", None)),
        ("output", getattr(result, "sequence", None)),
    ):
        if isinstance(value, str):
            result_summary.update(
                {
                    f"{prefix}_sequence_length": len(value),
                    f"{prefix}_sequence_sha256": hashlib.sha256(
                        value.encode()
                    ).hexdigest(),
                }
            )
    record_provider_call_result(
        provider="local_open",
        operation={
            "generate(track=sequence)": "esm3.generate_sequence",
            "generate(track=structure)": "esm3.generate_structure",
        }.get(operation, operation),
        model=model_name,
        provider_identity={
            "sdk": "esm",
            "sdk_source_revision": ESM_SDK_REVISION,
            "service": "local_open",
            "snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
            "weight_sha256": dict(sorted(LOCAL_ESM3_WEIGHT_SHA256.items())),
        },
        effective_seed=effective_seed,
        seed_control="torch_local",
        result_summary=result_summary,
    )


def configured_runtime_fingerprint(
    *,
    device: str,
    performance_settings: Mapping[str, Any] | None = None,
) -> str:
    """Build the safe fingerprint trusted configuration must declare."""
    _, torch_version = _validate_device(device)
    return _runtime_fingerprint(
        device=device,
        torch_version=torch_version,
        performance_settings=performance_settings or {},
    )
