"""Module-owned read-only actions over immutable published values."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core.parameters.model import ParameterContract


class ResultActionError(ValueError):
    """A requested read-only action is not applicable to the selected value."""


@dataclass(frozen=True, slots=True)
class ResultActionDefinition:
    action_id: str
    port_type_id: str
    parameters: ParameterContract
    apply: Callable[[bytes, Mapping[str, Any]], dict[str, Any]]
