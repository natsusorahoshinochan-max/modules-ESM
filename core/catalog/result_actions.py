"""Module-owned read-only actions over immutable published values."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from core.parameters.model import ParameterContract
from datatypes.candidate import CandidateDataReference


class ResultActionError(ValueError):
    """A requested read-only action is not applicable to the selected value."""


@dataclass(frozen=True, slots=True)
class ResultActionInput:
    name: str
    port_type_id: str
    multiplicity: Literal['one', 'many'] = 'one'
    required: bool = True


@dataclass(frozen=True, slots=True)
class ResultActionValue:
    """An immutable published input and its actual Candidate references."""
    body: bytes
    candidate_references: tuple[CandidateDataReference, ...]
    value_content_digest: str


ResultActionInputs = Mapping[str, Mapping[str, tuple[ResultActionValue, ...]]]


@dataclass(frozen=True, slots=True)
class ResultActionDefinition:
    action_id: str
    inputs: tuple[ResultActionInput, ...]
    parameters: ParameterContract
    apply: Callable[[ResultActionInputs, Mapping[str, Any]], dict[str, Any]]
