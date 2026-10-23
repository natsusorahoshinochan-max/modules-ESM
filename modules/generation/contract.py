"""Generation operation's public multitrack call, implemented by tool adapters."""
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class GenerateRequest:
    track: str
    tracks: dict[str, Any]
    target_file: str | None = None
    conditions: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class GenerateResult:
    tracks: dict[str, Any]
    values_file: str
    parameters: dict[str, Any]
    actual_seed: int | None = None
    coordinate_role: str = 'absent'
    structure_file: str | None = None
