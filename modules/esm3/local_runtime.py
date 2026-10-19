"""Load the fixed native open model from existing local assets only."""
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from types import FunctionType
from typing import Any, Callable, Iterator, cast

_LOCAL_ESM3_SDK_ROOT_LOCK = RLock()
LOCAL_ESM3_LSH_TABLE_PATH = "data/hyperplanes_8bit_58641.npz"

def _bind_builder_to_root(
    builder: FunctionType,
    root: Path,
) -> FunctionType:
    """Clone an SDK builder with a private data-root binding."""
    builder_globals = dict(builder.__globals__)
    builder_globals["data_root"] = lambda model: root
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
                raise ValueError(
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
    snapshot_path: Path,
    default_device: Any,
) -> Callable[[Any], Any]:
    """Bind one SDK builder directly to the admitted snapshot data root."""
    bound_builder = _bind_builder_to_root(builder, snapshot_path)

    def load(device: Any = None) -> Any:
        with _sdk_snapshot_root(snapshot_path):
            return bound_builder(
                default_device if device is None else device
            )

    return load


def load_local_esm3_client(
    runtime,
    *,
    model_name: str,
) -> Any:
    """Load the configured local model on explicit demand."""
    import torch
    import esm.pretrained as esm_pretrained

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
            Path(runtime.model_path),
            torch.device(runtime.device),
        )
        for name, builder in required_builders.items()
    }
    client = bound[model_name](torch.device(runtime.device))
    client.structure_encoder_fn = bound["esm3_structure_encoder_v0"]
    client.structure_decoder_fn = bound["esm3_structure_decoder_v0"]
    client.function_decoder_fn = bound["esm3_function_decoder_v0"]
    client.get_structure_encoder()
    client.get_structure_decoder()
    client.get_function_decoder()
    client.tokenizers.function.lsh_path = (
        Path(runtime.model_path) / LOCAL_ESM3_LSH_TABLE_PATH
    )
    client = client.float()
    return client

