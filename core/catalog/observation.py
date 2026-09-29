"""Fixed scientific Observation contracts shared by declarations and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from datatypes.exact_reference import ExactContractReference
from datatypes.observation import ObservationContextProfile

SourceDirection = Literal["input", "output"]
ObservationMultiplicity = Literal["one", "one_or_more", "zero_or_more"]
PropagationMode = Literal["pass_through", "union", "filter"]
AbsentInputPolicy = Literal["reject", "ignore"]


@dataclass(frozen=True, slots=True)
class ObservationPortSource:
    direction: SourceDirection
    port: str


@dataclass(frozen=True, slots=True)
class ProducedObservation:
    output_port: str
    output_partition: str
    metric: ExactContractReference
    context_profile: ObservationContextProfile
    subject_input: str
    guaranteed_multiplicity: ObservationMultiplicity
    reference_source: ObservationPortSource | None = None
    pairing_source: ObservationPortSource | None = None
    axis_source: ObservationPortSource | None = None
    method_source: ObservationPortSource | None = None


@dataclass(frozen=True, slots=True)
class ObservationPropagationFilter:
    source_partition: str | None = None
    metric: ExactContractReference | None = None
    method: ExactContractReference | None = None
    context_profile: ObservationContextProfile | None = None


@dataclass(frozen=True, slots=True)
class ObservationPropagation:
    mode: PropagationMode
    output_port: str
    input_ports: tuple[str, ...]
    filter: ObservationPropagationFilter | None = None
    absent_input_policy: AbsentInputPolicy = "reject"
