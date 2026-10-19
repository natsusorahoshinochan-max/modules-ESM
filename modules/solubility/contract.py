"""Public sequence-solubility tool call contract; see TOOL.md."""
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SolubilityRequest:
    sequences: tuple[str, ...]


@dataclass(frozen=True)
class SolubilityResult:
    method: str
    parameters: Mapping[str, Any]
    values: tuple[Mapping[str, Mapping[str, Any]], ...]
    output_file: str
    context: Mapping[str, Any]
