"""Public ProteinMPNN tool calling contract shared by design and scoring tasks."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MPNNRequest:
    structure_path: str
    structure_format: str
    # None designs; a complete chain -> sequence mapping scores without sampling.
    sequences: dict[str, str] | None = None
    # Fixed random seed proposal used only when the selected tool seed is zero.
    random_seed: int | None = None
    complete_target: bool = False
    conditions: dict[str, Any] | None = None


@dataclass(frozen=True)
class MPNNResult:
    positions: list[dict[str, Any]]
    samples: list[dict[str, Any]]
    actual_seed: int
    parameters: dict[str, Any]
