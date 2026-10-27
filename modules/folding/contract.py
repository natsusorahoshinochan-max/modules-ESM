"""Public sequence prediction tool contract; see FORMAT.md and TOOL.md."""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PredictionRequest:
    sequence: str
    object_id: str


@dataclass(frozen=True)
class PredictionResult:
    structure_path: str
    structure_format: str = 'pdb'
    plddt: list[float] | None = None
    ptm: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)
