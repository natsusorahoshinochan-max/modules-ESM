"""Module-owned projections of immutable published typed values."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResultReaderDefinition:
    port_type_id: str
    kind: str
    read: Callable[[bytes], dict[str, Any]]
