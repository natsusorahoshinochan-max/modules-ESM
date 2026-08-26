"""Local-open ESM-3 runtime loading and evidence."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import shutil
import tempfile
from threading import RLock
from types import FunctionType
from typing import Any, cast
import weakref

from core.operation import (
    OperationResources,
    ReadinessResult,
    retain_secondary_cleanup_exception,
)
from core.local_torch_device import (
    expected_local_torch_device,
    local_torch_device_is_available,
)
from .adapter import (
    ESM3Confidence,
    _BaseESM3Adapter,
    require_provider_protein,
)


LOCAL_ESM3_MODEL = "esm3_sm_open_v1"
LOCAL_ESM3_SNAPSHOT_SOURCE = "biohub/esm3-sm-open-v1"
LOCAL_ESM3_WEIGHT_FILES = (
    "data/weights/esm3_sm_open_v1.pth",
    "data/weights/esm3_structure_encoder_v0.pth",
    "data/weights/esm3_structure_decoder_v0.pth",
    "data/weights/esm3_function_decoder_v0.pth",
)
_LOCAL_ESM3_SDK_ROOT_LOCK = RLock()


class LocalESM3RuntimeUnavailable(RuntimeError):
    """The local ESM-3 runtime is unavailable."""


@dataclass(frozen=True, slots=True)
class LocalESM3Runtime:
    """Resolved paths admitted by the local ESM3 Binding."""

    snapshot_path: Path
    runtime_directory: Path
    device: str


def local_runtime_structurally_available() -> bool:
    """Check import prerequisites without loading model weights."""
    return not (
        importlib.util.find_spec("esm") is None
        or importlib.util.find_spec("esm.pretrained") is None
        or importlib.util.find_spec("esm.models.esm3") is None
        or importlib.util.find_spec("esm.sdk.api") is None
        or importlib.util.find_spec("torch") is None
    )


def _configured_path(environment: Mapping[str, Any], key: str) -> Path:
    try:
        path = cast(Path, environment[key]).resolve(strict=True)
    except OSError as error:
        raise LocalESM3RuntimeUnavailable(
            f"local ESM-3 {key} is unavailable"
        ) from error
    if not path.is_dir():
        raise LocalESM3RuntimeUnavailable(
            f"local ESM-3 {key} is not a directory"
        )
    return path


def _validate_device() -> str:
    expected_device = expected_local_torch_device()
    try:
        import torch
    except ImportError as error:
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 runtime is unavailable"
        ) from error
    if not local_torch_device_is_available(torch, expected_device):
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 policy-selected Torch device is unavailable"
        )
    return expected_device


def resolve_local_runtime(
    environment: Mapping[str, Any],
) -> LocalESM3Runtime:
    """Resolve configured paths before entering the local Provider."""
    snapshot_path = _configured_path(environment, "model_snapshot_path")
    runtime_directory = _configured_path(environment, "runtime_directory")
    device = _validate_device()
    if any(
        not (snapshot_path / relative_path).is_file()
        for relative_path in LOCAL_ESM3_WEIGHT_FILES
    ):
        raise LocalESM3RuntimeUnavailable(
            "local ESM-3 model files are unavailable"
        )
    return LocalESM3Runtime(
        snapshot_path=snapshot_path,
        runtime_directory=runtime_directory,
        device=device,
    )


def _trusted_local_runtime(
    environment: Mapping[str, Any],
) -> LocalESM3Runtime:
    """Read runtime facts already admitted by per-run Binding readiness."""
    snapshot_path = Path(environment["model_snapshot_path"])
    return LocalESM3Runtime(
        snapshot_path=snapshot_path,
        runtime_directory=Path(environment["runtime_directory"]),
        device=expected_local_torch_device(),
    )


def local_readiness(environment: Mapping[str, Any]) -> ReadinessResult:
    """Return one bounded, redacted conclusion for the selected local Binding."""
    try:
        resolve_local_runtime(environment)
    except LocalESM3RuntimeUnavailable:
        return ReadinessResult(
            False,
            proof_source="direct-observation",
            reason_code="local_runtime_unavailable",
        )
    return ReadinessResult(True, proof_source="direct-observation")


def stage_local_runtime(runtime: LocalESM3Runtime) -> Path:
    """Stage the configured model files for the SDK loader."""
    staged_root = Path(
        tempfile.mkdtemp(
            prefix="esm3-sm-open-v1-",
            dir=runtime.runtime_directory,
        )
    )
    staged_root.chmod(0o700)
    try:
        for relative_path in LOCAL_ESM3_WEIGHT_FILES:
            source = runtime.snapshot_path / relative_path
            destination = staged_root / relative_path
            destination.parent.mkdir(
                mode=0o700,
                parents=True,
                exist_ok=True,
            )
            shutil.copyfile(source, destination)
        return staged_root
    except BaseException as error:
        try:
            shutil.rmtree(staged_root)
        except BaseException as cleanup_error:
            retain_secondary_cleanup_exception(error, cleanup_error)
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


@contextmanager
def _sdk_snapshot_root(snapshot_path: Path) -> Iterator[None]:
    """Temporarily bind SDK-owned ESM-3 lookups to one snapshot."""
    import esm.utils.constants.esm3 as esm3_constants

    with _LOCAL_ESM3_SDK_ROOT_LOCK:
        original_data_root = esm3_constants.data_root

        def snapshot_data_root(model: str) -> Path:
            if model != "esm3":
                raise LocalESM3RuntimeUnavailable(
                    "local ESM-3 SDK requested an undeclared model root"
                )
            return snapshot_path

        esm3_constants.data_root = snapshot_data_root
        try:
            yield
        finally:
            esm3_constants.data_root = original_data_root


def _bind_builder_to_local_roots(
    builder: FunctionType,
    staged_root: Path,
    snapshot_path: Path,
    default_device: Any,
) -> Callable[[Any], Any]:
    """Bind one SDK builder to staged weights and snapshot data."""
    staged_builder = _bind_builder_to_staged_root(builder, staged_root)

    def load(device: Any = None) -> Any:
        with _sdk_snapshot_root(snapshot_path):
            return staged_builder(
                default_device if device is None else device
            )

    return load


def load_local_esm3_client(
    runtime: LocalESM3Runtime,
    *,
    model_name: str,
) -> Any:
    """Load the configured local model on explicit demand."""
    import torch
    import esm.pretrained as esm_pretrained
    import esm.utils.constants.esm3 as esm3_constants

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
            name: _bind_builder_to_local_roots(
                builder,
                staged_root,
                runtime.snapshot_path,
                torch.device(runtime.device),
            )
            for name, builder in required_builders.items()
        }
        client = bound[model_name](torch.device(runtime.device))
        client.structure_encoder_fn = bound["esm3_structure_encoder_v0"]
        client.structure_decoder_fn = bound["esm3_structure_decoder_v0"]
        client.function_decoder_fn = bound["esm3_function_decoder_v0"]
        client.tokenizers.function.lsh_path = (
            runtime.snapshot_path / esm3_constants.LSH_TABLE_PATHS["8bit"]
        )
        client = client.float()
        client._protein_workbench_staged_root = staged_root
        client._protein_workbench_staged_cleanup = weakref.finalize(
            client,
            shutil.rmtree,
            staged_root,
        )
        return client
    except BaseException as error:
        try:
            shutil.rmtree(staged_root)
        except BaseException as cleanup_error:
            retain_secondary_cleanup_exception(error, cleanup_error)
        raise


def release_local_esm3_client(client: Any) -> None:
    """Release private staged weights owned by an internally loaded client."""
    shutil.rmtree(client._protein_workbench_staged_root)
    client._protein_workbench_staged_cleanup.detach()


def call_local_provider(
    client: Any,
    protein: Any,
    config: Any,
    operation: str,
    *,
    effective_seed: int,
    device: str,
) -> Any:
    """Execute one local call under the exact derived Torch seed."""
    import torch
    from esm.sdk.api import ESMProteinError

    try:
        torch_device = torch.device(device)
        fork_devices = (
            [torch.cuda.current_device()]
            if torch_device.type == "cuda"
            else []
        )
        with torch.random.fork_rng(devices=fork_devices):
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
        resources: OperationResources,
        model_name: str,
    ) -> None:
        super().__init__(
            resources=resources,
            model_name=model_name,
            exact_seed_control=True,
        )
        self._environment = environment
        self._resolved_client: Any | None = None
        self._provider_lifecycle = ExitStack()

    def __enter__(self) -> LocalESM3Adapter:
        self._provider_lifecycle.enter_context(
            self._resources.local_provider("local-esm3")
        )
        return self

    def _client(self) -> Any:
        if self._resolved_client is not None:
            return self._resolved_client
        runtime = _trusted_local_runtime(self._environment)
        client = load_local_esm3_client(
            runtime,
            model_name=self._model_name,
        )
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
            device=expected_local_torch_device(),
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
        primary = (
            cast(BaseException, exception)
            if exception is not None
            else None
        )
        try:
            client = self._resolved_client
            self._resolved_client = None
            if client is not None:
                release_local_esm3_client(client)
        except BaseException as cleanup_error:
            if primary is None:
                primary = cleanup_error
            else:
                retain_secondary_cleanup_exception(primary, cleanup_error)
        try:
            self._provider_lifecycle.__exit__(
                exception_type,
                exception,
                traceback,
            )
        except BaseException as cleanup_error:
            if primary is None:
                primary = cleanup_error
            else:
                retain_secondary_cleanup_exception(primary, cleanup_error)
        if exception is None and primary is not None:
            raise primary
