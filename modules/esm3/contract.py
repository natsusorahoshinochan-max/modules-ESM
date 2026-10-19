"""Public, task-independent ESM3 generate calling contract; see TOOL.md."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ESM3Request:
    track: str
    tracks: dict[str, Any]


@dataclass(frozen=True)
class ESM3Result:
    tracks: dict[str, Any]
    # Closed JSON file relative to runtime.workdir: all native tracks and metrics.
    values_file: str
    parameters: dict[str, Any]
    actual_seed: int | None = None
