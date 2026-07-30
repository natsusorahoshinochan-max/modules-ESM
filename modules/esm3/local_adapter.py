"""Exact local-open ESM-3 runtime validation, loading, and evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import FunctionType
from typing import Any
import weakref

from core import ReadinessResult, canonical_sha256
from modules.provider_contract import (
    LOCAL_ESM3_SNAPSHOT_REVISION,
    LOCAL_ESM3_WEIGHT_SHA256,
    validate_installed_provider_checkout,
)

from .adapter import ESM_SDK_REVISION, require_provider_protein


LOCAL_ESM3_MODEL = "esm3_sm_open_v1"
LOCAL_ESM3_SNAPSHOT_SOURCE = "biohub/esm3-sm-open-v1"
LOCAL_ESM3_DEVICE = "cpu"
LOCAL_ESM3_TORCH_VERSION = "2.13.0"
LOCAL_ESM3_PERFORMANCE_SETTINGS: Mapping[str, Any] = {}


@dataclass(frozen=True, slots=True)
class LocalESM3Runtime:
    """Resolved private paths paired with one safe runtime identity."""

    snapshot_path: Path
    runtime_directory: Path
    device: str
    performance_settings: Mapping[str, Any]
    safe_fingerprint: str
    artifact_sources: Mapping[str, Path] = field(default_factory=dict)


def local_runtime_structurally_available() -> bool:
    """Check import/source prerequisites without loading model weights."""
    if (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("torch") is None
    ):
        return False
    try:
        validate_installed_provider_checkout("esm", ESM_SDK_REVISION)
        import torch
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return str(torch.__version__) == LOCAL_ESM3_TORCH_VERSION


def _regular_file_sha256(path: Path) -> str:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeError(
                "required local ESM-3 model artifact is not regular"
            )
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
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
            raise RuntimeError(
                "local ESM-3 model artifact changed during validation"
            )
        return digest.hexdigest()
    except OSError as error:
        raise RuntimeError(
            "local ESM-3 model artifact could not be validated"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _snapshot_artifact_source(
    snapshot_path: Path,
    relative_path: str,
    expected_digest: str,
) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuntimeError("local ESM-3 model artifact path is invalid")
    try:
        parent = snapshot_path
        for component in relative.parts[:-1]:
            parent = parent / component
            metadata = parent.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
                metadata.st_mode
            ):
                raise RuntimeError(
                    "local ESM-3 snapshot directory is not regular"
                )
        entry = parent / relative.parts[-1]
        metadata = entry.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            target_value = os.readlink(entry)
            if Path(target_value).is_absolute():
                raise RuntimeError(
                    "local ESM-3 snapshot link is not repository-contained"
                )
            target = (entry.parent / target_value).resolve(strict=True)
            repository_root = snapshot_path.parent.parent.resolve(strict=True)
            expected_blob_root = repository_root / "blobs"
            if (
                target.parent != expected_blob_root
                or target.name != expected_digest
            ):
                raise RuntimeError(
                    "local ESM-3 snapshot link is not repository-contained"
                )
        elif stat.S_ISREG(metadata.st_mode):
            target = entry
        else:
            raise RuntimeError(
                "required local ESM-3 model artifact is not regular"
            )
    except OSError as error:
        raise RuntimeError(
            "local ESM-3 model artifact could not be validated"
        ) from error
    if _regular_file_sha256(target) != expected_digest:
        raise RuntimeError("local ESM-3 model artifact identity mismatch")
    return target


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
    if not isinstance(raw, Mapping) or dict(raw) != dict(
        LOCAL_ESM3_PERFORMANCE_SETTINGS
    ):
        raise RuntimeError(
            "local ESM-3 performance settings do not match the Binding"
        )
    return dict(LOCAL_ESM3_PERFORMANCE_SETTINGS)


def _validate_device(device: object) -> tuple[str, str]:
    if device != LOCAL_ESM3_DEVICE:
        raise RuntimeError("local ESM-3 device does not match the Binding")
    import torch

    torch_version = str(torch.__version__)
    if torch_version != LOCAL_ESM3_TORCH_VERSION:
        raise RuntimeError(
            "local ESM-3 Torch runtime does not match the Binding"
        )
    return LOCAL_ESM3_DEVICE, torch_version


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
    device, torch_version = _validate_device(environment.get("device"))
    performance_settings = _validated_performance_settings(environment)
    artifact_sources: dict[str, Path] = {}
    for relative_path, expected_digest in LOCAL_ESM3_WEIGHT_SHA256.items():
        artifact_sources[relative_path] = _snapshot_artifact_source(
            snapshot_path,
            relative_path,
            expected_digest,
        )
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
        artifact_sources=artifact_sources,
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


def _copy_verified_artifact(
    source: Path,
    destination: Path,
    expected_digest: str,
) -> None:
    """Copy one already-resolved artifact without following a replacement."""
    source_descriptor: int | None = None
    destination_descriptor: int | None = None
    try:
        source_descriptor = os.open(
            source,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(source_descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeError(
                "required local ESM-3 model artifact is not regular"
            )
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        digest = hashlib.sha256()
        while chunk := os.read(source_descriptor, 1024 * 1024):
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination_descriptor, view)
                view = view[written:]
        os.fsync(destination_descriptor)
        after = os.fstat(source_descriptor)
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
            raise RuntimeError(
                "local ESM-3 model artifact changed during staging"
            )
        if digest.hexdigest() != expected_digest:
            raise RuntimeError("local ESM-3 model artifact identity mismatch")
    except OSError as error:
        raise RuntimeError(
            "local ESM-3 model artifact could not be staged"
        ) from error
    finally:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
        if source_descriptor is not None:
            os.close(source_descriptor)


def stage_local_runtime(runtime: LocalESM3Runtime) -> Path:
    """Stage validated weights as private regular files for provider loading."""
    staged_root = Path(
        tempfile.mkdtemp(
            prefix="esm3-sm-open-v1-",
            dir=runtime.runtime_directory,
        )
    )
    staged_root.chmod(0o700)
    try:
        for relative_path, expected_digest in (
            LOCAL_ESM3_WEIGHT_SHA256.items()
        ):
            source = runtime.artifact_sources.get(relative_path)
            if not isinstance(source, Path):
                raise RuntimeError(
                    "local ESM-3 validated artifact source is unavailable"
                )
            destination = staged_root / relative_path
            destination.parent.mkdir(
                mode=0o700,
                parents=True,
                exist_ok=True,
            )
            _copy_verified_artifact(
                source,
                destination,
                expected_digest,
            )
        return staged_root
    except BaseException:
        shutil.rmtree(staged_root)
        raise


def _bind_builder_to_staged_root(
    builder: Any,
    staged_root: Path,
) -> FunctionType:
    """Clone an SDK builder with a private, immutable data-root binding."""
    if not isinstance(builder, FunctionType):
        raise RuntimeError("local ESM-3 provider builder has an unsafe type")
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
    if model_name != LOCAL_ESM3_MODEL:
        raise RuntimeError("local ESM-3 Binding requested an unknown model")
    if runtime is None:
        runtime = resolve_local_runtime(environment)
    import torch
    from esm.models.esm3 import ESM3
    import esm.pretrained as esm_pretrained

    staged_root = stage_local_runtime(runtime)
    try:
        builders = esm_pretrained.LOCAL_MODEL_REGISTRY
        required_builders = {
            name: builders.get(name)
            for name in (
                LOCAL_ESM3_MODEL,
                "esm3_structure_encoder_v0",
                "esm3_structure_decoder_v0",
                "esm3_function_decoder_v0",
            )
        }
        if any(not callable(builder) for builder in required_builders.values()):
            raise RuntimeError("local ESM-3 provider builders are incomplete")
        bound = {
            name: _bind_builder_to_staged_root(builder, staged_root)
            for name, builder in required_builders.items()
        }
        client = bound[LOCAL_ESM3_MODEL](torch.device(runtime.device))
        if not isinstance(client, ESM3):
            raise RuntimeError("local ESM-3 provider returned the wrong client")
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
    """Build exact local call identity before entering the model seam."""
    track_identity = _track_identity(protein)
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
) -> None:
    """Persist safe local provider identity after the Engine Invocation."""
    from modules.provider_evidence import record_provider_call_result

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
