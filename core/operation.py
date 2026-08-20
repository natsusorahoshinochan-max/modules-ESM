"""Typed execution interface for one resolved scientific operation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Protocol

from datatypes import (
    CandidateDataReference,
    ExactContractReference,
    ResidueAxisReference,
)

if TYPE_CHECKING:
    from core.run_execution_v2 import RunResources
    from core.scoring_v2 import (
        ResolvedObservationSelector,
        ResolvedSelectionObjective,
    )


PortMultiplicity = Literal["one", "many"]


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
class AdmittedValue:
    """One immutable canonical value and every Port-owned projection."""

    value: Any
    canonical_bytes: bytes
    content_digest: str
    candidate_data: tuple[CandidateDataReference, ...] = ()
    scientific_axes: tuple[ResidueAxisReference, ...] = ()
    observation_methods: tuple[ExactContractReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _freeze_container(self.value))
        object.__setattr__(self, "canonical_bytes", bytes(self.canonical_bytes))
        candidate_data = tuple(self.candidate_data)
        if any(
            type(reference) is not CandidateDataReference
            for reference in candidate_data
        ):
            raise TypeError(
                "candidate_data entries must be CandidateDataReference values"
            )
        object.__setattr__(self, "candidate_data", candidate_data)
        scientific_axes = tuple(self.scientific_axes)
        if any(
            type(reference) is not ResidueAxisReference
            for reference in scientific_axes
        ):
            raise TypeError(
                "scientific_axes entries must be ResidueAxisReference values"
            )
        object.__setattr__(self, "scientific_axes", scientific_axes)
        observation_methods = tuple(self.observation_methods)
        if any(
            type(reference) is not ExactContractReference
            or reference.contract_kind != "method"
            for reference in observation_methods
        ):
            raise TypeError(
                "observation_methods entries must be exact Method references"
            )
        object.__setattr__(
            self,
            "observation_methods",
            observation_methods,
        )


@dataclass(frozen=True, slots=True)
class AdmittedPort:
    """Complete admitted record for one exact input or output Port."""

    port_type: Mapping[str, Any]
    multiplicity: PortMultiplicity
    values: tuple[AdmittedValue, ...]
    content_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "port_type",
            MappingProxyType(dict(self.port_type)),
        )
        values = tuple(self.values)
        if any(type(value) is not AdmittedValue for value in values):
            raise TypeError("values must contain exact AdmittedValue records")
        if self.multiplicity not in {"one", "many"}:
            raise ValueError("multiplicity must be one or many")
        object.__setattr__(self, "values", values)

    @property
    def value(self) -> Any:
        """Return the admitted scientific value in its declared multiplicity."""
        if self.multiplicity == "many":
            return tuple(item.value for item in self.values)
        return self.values[0].value

    def __bool__(self) -> bool:
        return bool(self.values)

    @property
    def value_content_digests(self) -> tuple[str, ...]:
        return tuple(value.content_digest for value in self.values)

    @property
    def candidate_data(self) -> tuple[CandidateDataReference, ...]:
        return tuple(
            reference
            for value in self.values
            for reference in value.candidate_data
        )

    @property
    def scientific_axes(self) -> tuple[ResidueAxisReference, ...]:
        return tuple(
            reference
            for value in self.values
            for reference in value.scientific_axes
        )

    @property
    def observation_methods(self) -> tuple[ExactContractReference, ...]:
        return tuple(
            reference
            for value in self.values
            for reference in value.observation_methods
        )


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

    inputs: Mapping[str, AdmittedPort]
    node_parameters: Mapping[str, Any]
    binding_parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if any(
            type(port_name) is not str or type(record) is not AdmittedPort
            for port_name, record in self.inputs.items()
        ):
            raise TypeError("inputs must contain complete AdmittedPort records")
        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(dict(self.inputs)),
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


class ScientificOperation(Protocol):
    """One canonical scientific implementation behind a Binding."""

    def execute(self, call: OperationCall) -> Mapping[str, Any]: ...
