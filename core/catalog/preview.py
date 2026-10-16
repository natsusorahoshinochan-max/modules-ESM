"""Module-owned explanations of a valid, unpublished port value."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ValuePreviewDefinition:
    projection_id: str
    port_type_id: str
    title: str
    describe: Callable[[Any], Mapping[str, Any]]
