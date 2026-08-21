"""Compiler-resolved plans for Produced Observation admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from datatypes.exact_reference import ExactContractReference


SourceDirection = Literal["input", "output"]
ObservationMultiplicity = Literal["one", "one_or_more", "zero_or_more"]
PropagationMode = Literal["pass_through", "union", "filter"]
AbsentInputPolicy = Literal["reject", "ignore"]


class ObservationPlanError(ValueError):
    """Compiler-supplied observation facts are incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class IntrinsicContextProfile:
    """Compiler-resolved intrinsic Observation Context contract."""

    kind: Literal["intrinsic"] = "intrinsic"


@dataclass(frozen=True, slots=True)
class CalibrationContextProfile:
    """Compiler-resolved calibration Observation Context contract."""

    calibration_metric: str
    calibration_value: int | float
    calibration_unit: str
    population_id: str
    kind: Literal["calibration"] = "calibration"


@dataclass(frozen=True, slots=True)
class PairwiseContextProfile:
    """Compiler-resolved pairwise Observation Context contract."""

    subject_role: str
    reference_role: str
    pairing_mode: str
    normalization: str
    kind: Literal["pairwise"] = "pairwise"


ObservationContextProfile = (
    IntrinsicContextProfile
    | CalibrationContextProfile
    | PairwiseContextProfile
)


def admit_context_profile(
    value: Mapping[str, Any] | ObservationContextProfile,
) -> ObservationContextProfile:
    """Resolve one Catalog Context profile into a closed typed contract."""
    if isinstance(
        value,
        (
            IntrinsicContextProfile,
            CalibrationContextProfile,
            PairwiseContextProfile,
        ),
    ):
        return value
    if not isinstance(value, Mapping):
        raise ObservationPlanError("Observation Context profile must be an object")
    kind = value.get("kind")
    if kind == "intrinsic" and set(value) == {"kind"}:
        return IntrinsicContextProfile()
    if kind == "calibration" and set(value) == {
        "kind",
        "calibration_metric",
        "calibration_value",
        "calibration_unit",
        "population_id",
    }:
        calibration_value = value["calibration_value"]
        if (
            type(value["calibration_metric"]) is not str
            or type(calibration_value) not in {int, float}
            or type(value["calibration_unit"]) is not str
            or type(value["population_id"]) is not str
        ):
            raise ObservationPlanError(
                "Calibration Context profile has invalid typed fields"
            )
        return CalibrationContextProfile(
            calibration_metric=value["calibration_metric"],
            calibration_value=calibration_value,
            calibration_unit=value["calibration_unit"],
            population_id=value["population_id"],
        )
    if kind == "pairwise" and set(value) == {
        "kind",
        "subject_role",
        "reference_role",
        "pairing_mode",
        "normalization",
    }:
        fields = (
            value["subject_role"],
            value["reference_role"],
            value["pairing_mode"],
            value["normalization"],
        )
        if any(type(field) is not str for field in fields):
            raise ObservationPlanError(
                "Pairwise Context profile has invalid typed fields"
            )
        return PairwiseContextProfile(
            subject_role=value["subject_role"],
            reference_role=value["reference_role"],
            pairing_mode=value["pairing_mode"],
            normalization=value["normalization"],
        )
    raise ObservationPlanError("Observation Context profile is not closed")


@dataclass(frozen=True, slots=True)
class StructureAlignmentEvidencePlan:
    """Typed source and normalization facts for alignment-backed Metrics."""

    source_direction: SourceDirection
    source_port: str
    normalization_length_source: Literal[
        "aligned_atom_count",
        "reference_axis_residue_count",
    ]


@dataclass(frozen=True, slots=True)
class ResolvedMetricFacts:
    """Scientific validation facts for one exact Metric Definition."""

    reference: ExactContractReference
    value_shape: str
    minimum: int | float
    maximum: int | float
    allow_null: bool
    require_finite: bool
    exact_binary32: bool
    requires_residue_axis: bool
    structure_alignment_evidence: StructureAlignmentEvidencePlan | None = None

    def __post_init__(self) -> None:
        if (
            type(self.reference) is not ExactContractReference
            or self.reference.contract_kind != "metric"
        ):
            raise ObservationPlanError(
                "Resolved Metric facts require an exact Metric reference"
            )


@dataclass(frozen=True, slots=True)
class ResolvedProducedObservation:
    """One compiler-resolved Produced Observation declaration."""

    output_port: str
    output_partition: str
    metric: ExactContractReference
    context_profile: ObservationContextProfile
    subject_grain: str
    source_role: str
    subject_direction: SourceDirection
    subject_port: str
    guaranteed_multiplicity: ObservationMultiplicity
    reference_direction: SourceDirection | None = None
    reference_port: str | None = None
    pairing_direction: SourceDirection | None = None
    pairing_port: str | None = None
    axis_direction: SourceDirection | None = None
    axis_port: str | None = None
    method_direction: SourceDirection | None = None
    method_port: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.metric) is not ExactContractReference
            or self.metric.contract_kind != "metric"
        ):
            raise ObservationPlanError(
                "Produced Observation requires an exact Metric reference"
            )
        object.__setattr__(
            self,
            "context_profile",
            admit_context_profile(self.context_profile),
        )


@dataclass(frozen=True, slots=True)
class ObservationPropagationFilter:
    """Typed exact filter for one controlled propagation operation."""

    source_partition: str | None = None
    metric: ExactContractReference | None = None
    method: ExactContractReference | None = None
    context_profile: ObservationContextProfile | None = None

    def __post_init__(self) -> None:
        if self.metric is not None and self.metric.contract_kind != "metric":
            raise ObservationPlanError(
                "Observation propagation filter requires a Metric reference"
            )
        if self.method is not None and self.method.contract_kind != "method":
            raise ObservationPlanError(
                "Observation propagation filter requires a Method reference"
            )
        if self.context_profile is not None:
            object.__setattr__(
                self,
                "context_profile",
                admit_context_profile(self.context_profile),
            )


@dataclass(frozen=True, slots=True)
class ObservationPropagationPlan:
    """Compiler-resolved controlled Score Collection propagation."""

    mode: PropagationMode
    output_port: str
    input_ports: tuple[str, ...]
    filter: ObservationPropagationFilter | None = None
    absent_input_policy: AbsentInputPolicy = "reject"

    def __post_init__(self) -> None:
        input_ports = tuple(self.input_ports)
        if not input_ports:
            raise ObservationPlanError(
                "Observation propagation requires an input Port"
            )
        if self.mode == "filter" and self.filter is None:
            raise ObservationPlanError(
                "Filter propagation requires an exact filter"
            )
        if self.mode != "filter" and self.filter is not None:
            raise ObservationPlanError(
                "Only filter propagation accepts a filter"
            )
        object.__setattr__(self, "input_ports", input_ports)


@dataclass(frozen=True, slots=True)
class ProducedObservationPlan:
    """Closed compiler output consumed by Observation Admission."""

    binding_method: ExactContractReference
    observations: tuple[ResolvedProducedObservation, ...] = ()
    metric_facts: Mapping[ExactContractReference, ResolvedMetricFacts] = field(
        default_factory=dict,
        repr=False,
    )
    propagation: ObservationPropagationPlan | None = None

    def __post_init__(self) -> None:
        if (
            type(self.binding_method) is not ExactContractReference
            or self.binding_method.contract_kind != "method"
        ):
            raise ObservationPlanError(
                "Produced Observation plan requires an exact Binding Method"
            )
        observations = tuple(self.observations)
        facts = dict(self.metric_facts)
        required_metrics = {observation.metric for observation in observations}
        if set(facts) != required_metrics:
            raise ObservationPlanError(
                "Produced Observation Metric facts are not an exact closure"
            )
        if any(facts[reference].reference != reference for reference in facts):
            raise ObservationPlanError(
                "Produced Observation Metric fact identity is inconsistent"
            )
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "metric_facts", MappingProxyType(facts))

    def observations_for_output(
        self,
        output_port: str,
    ) -> tuple[ResolvedProducedObservation, ...]:
        """Return the exact declarations owned by one output Port."""
        return tuple(
            observation
            for observation in self.observations
            if observation.output_port == output_port
        )


def resolve_metric_facts(
    reference: ExactContractReference,
    descriptor: Mapping[str, Any],
) -> ResolvedMetricFacts:
    """Convert one compiler-resolved Metric descriptor to typed facts."""
    if reference.contract_kind != "metric":
        raise ObservationPlanError("Expected an exact Metric reference")
    value_shape = descriptor.get("value_shape")
    if value_shape not in {
        "scalar",
        "per_residue",
        "residue_vector",
        "residue_pair_matrix",
    }:
        raise ObservationPlanError(
            f"Produced Observation does not support Metric shape {value_shape!r}"
        )
    canonical_range = descriptor.get("canonical_range")
    if not isinstance(canonical_range, Mapping):
        raise ObservationPlanError("Metric canonical range is malformed")
    minimum = canonical_range.get("minimum")
    maximum = canonical_range.get("maximum")
    if (
        not isinstance(minimum, (int, float))
        or isinstance(minimum, bool)
        or not isinstance(maximum, (int, float))
        or isinstance(maximum, bool)
    ):
        raise ObservationPlanError("Metric canonical range is malformed")
    validation = descriptor.get("validation_contract")
    if not isinstance(validation, Mapping):
        raise ObservationPlanError("Metric validation contract is malformed")
    alignment = validation.get("structure_alignment_evidence")
    required_context_fields = (
        "evidence_content_digest",
        "evidence_method",
        "subject_axis_content_digest",
        "reference_axis_content_digest",
        "normalization_length",
        "aligned_atom_count",
    )
    if alignment is not None and (
        not isinstance(alignment, Mapping)
        or set(alignment)
        != {
            "source_direction",
            "source_port",
            "normalization_length_source",
            "required_context_fields",
        }
        or alignment.get("source_direction") != "input"
        or not isinstance(alignment.get("source_port"), str)
        or not alignment.get("source_port")
        or alignment.get("normalization_length_source")
        not in {"aligned_atom_count", "reference_axis_residue_count"}
        or tuple(alignment.get("required_context_fields", ()))
        != required_context_fields
    ):
        raise ObservationPlanError(
            "Metric structure-alignment evidence contract is malformed"
        )
    masking = validation.get("masking")
    aggregation = descriptor.get("aggregation_semantics")
    aggregated_residue_population = (
        value_shape == "scalar"
        and isinstance(aggregation, Mapping)
        and aggregation.get("kind") not in (None, "none")
        and type(aggregation.get("source_metric")) is str
        and bool(aggregation.get("source_metric"))
    )
    return ResolvedMetricFacts(
        reference=reference,
        value_shape=value_shape,
        minimum=minimum,
        maximum=maximum,
        allow_null=(
            isinstance(masking, Mapping)
            and masking.get("allow_null") is True
        ),
        require_finite=validation.get("finite") is True,
        exact_binary32=(
            validation.get("numeric_format") == "binary32"
            and validation.get("exact_round_trip") is True
        ),
        requires_residue_axis=(
            value_shape
            in {"per_residue", "residue_vector", "residue_pair_matrix"}
            or aggregated_residue_population
        ),
        structure_alignment_evidence=(
            None
            if alignment is None
            else StructureAlignmentEvidencePlan(
                source_direction=alignment["source_direction"],
                source_port=alignment["source_port"],
                normalization_length_source=alignment[
                    "normalization_length_source"
                ],
            )
        ),
    )
