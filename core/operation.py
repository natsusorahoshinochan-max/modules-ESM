"""Typed execution interface for one resolved scientific operation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

from core.scoring_v2 import (
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
)
from datatypes import CandidateDataReference, ExactContractReference

if TYPE_CHECKING:
    from core.run_execution_v2 import RunResources


def _freeze_container(value: Any) -> Any:
    """Freeze caller-owned containers without changing scientific value types."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_container(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_container(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class CandidatePairingIntentEntry:
    """Raw producer identities intended to form one exact Candidate pair."""

    subject_candidate_id: str
    reference_candidate_id: str


@dataclass(frozen=True, slots=True)
class CandidatePairingIntent:
    """Pre-admission pairing projected after Candidate identity normalization."""

    entries: tuple[CandidatePairingIntentEntry, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))


@dataclass(frozen=True, slots=True)
class InputContentDigests:
    """Content identities admitted for one exact input Port."""

    port_type_id: str
    value_content_digests: tuple[str, ...]
    candidate_data: tuple[CandidateDataReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "value_content_digests",
            tuple(self.value_content_digests),
        )
        candidate_data = tuple(self.candidate_data)
        if any(
            type(reference) is not CandidateDataReference
            for reference in candidate_data
        ):
            raise TypeError(
                "candidate_data entries must be CandidateDataReference values"
            )
        object.__setattr__(self, "candidate_data", candidate_data)


@dataclass(frozen=True, slots=True)
class ResolvedProducedObservation:
    """One Binding-declared Observation with an exact resolved Metric."""

    output_port: str
    output_partition: str
    metric: ExactContractReference
    context_profile: Mapping[str, Any]
    subject_grain: str
    source_role: str
    subject_direction: str
    subject_port: str
    guaranteed_multiplicity: str
    reference_direction: str | None = None
    reference_port: str | None = None
    pairing_direction: str | None = None
    pairing_port: str | None = None
    axis_direction: str | None = None
    axis_port: str | None = None
    method_direction: str | None = None
    method_port: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "context_profile",
            _freeze_container(self.context_profile),
        )


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Resolved facts available while constructing one scientific operation."""

    method: ExactContractReference
    produced_observations: tuple[ResolvedProducedObservation, ...]
    selection_objectives: tuple[ResolvedSelectionObjective, ...]
    observation_selectors: tuple[ResolvedObservationSelector, ...]
    environment: Mapping[str, Any]
    resources: RunResources

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "produced_observations",
            tuple(self.produced_observations),
        )
        object.__setattr__(
            self,
            "selection_objectives",
            tuple(self.selection_objectives),
        )
        object.__setattr__(
            self,
            "observation_selectors",
            tuple(self.observation_selectors),
        )
        object.__setattr__(self, "environment", _freeze_container(self.environment))


@dataclass(frozen=True, slots=True)
class OperationCall:
    """Immutable admitted values supplied to one scientific operation call."""

    inputs: Mapping[str, Any]
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]
    input_content_digests: Mapping[str, InputContentDigests]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "inputs",
            _freeze_container(self.inputs),
        )
        object.__setattr__(
            self,
            "node_parameters",
            _freeze_container(self.node_parameters),
        )
        object.__setattr__(
            self,
            "binding_parameters",
            _freeze_container(self.binding_parameters),
        )
        object.__setattr__(
            self,
            "input_content_digests",
            _freeze_container(self.input_content_digests),
        )


class ScientificOperation(Protocol):
    """One canonical scientific implementation behind a Binding."""

    def execute(self, call: OperationCall) -> Mapping[str, Any]: ...
