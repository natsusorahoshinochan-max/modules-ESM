"""Catalog-resolved plans for Produced Observation admission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from datatypes.exact_reference import ExactContractReference


from core.catalog.observation import ProducedObservation, ObservationPropagation, SourceDirection


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


@dataclass(frozen=True, slots=True)
class ProducedObservationPlan:
    """Closed Catalog startup facts consumed by Observation Admission."""

    binding_method: ExactContractReference
    observations: tuple[ProducedObservation, ...] = ()
    metric_facts: Mapping[ExactContractReference, ResolvedMetricFacts] = field(
        default_factory=dict,
        repr=False,
    )
    propagation: ObservationPropagation | None = None

    def observations_for_output(
        self,
        output_port: str,
    ) -> tuple[ProducedObservation, ...]:
        """Return the exact declarations owned by one output Port."""
        return tuple(
            observation
            for observation in self.observations
            if observation.output_port == output_port
        )


class MetricDefinitionFacts(Protocol):
    value_shape: str
    canonical_range: Mapping[str, Any]
    validation_contract: Mapping[str, Any]
    requires_residue_axis: bool


def resolve_metric_facts(
    reference: ExactContractReference,
    definition: MetricDefinitionFacts,
) -> ResolvedMetricFacts:
    """Translate one Builder-admitted Metric into Scoring plan facts."""
    value_shape = definition.value_shape
    minimum = definition.canonical_range["minimum"]
    maximum = definition.canonical_range["maximum"]
    validation = definition.validation_contract
    alignment = validation.get("structure_alignment_evidence")
    masking = validation.get("masking")
    return ResolvedMetricFacts(
        reference=reference,
        value_shape=value_shape,
        minimum=minimum,
        maximum=maximum,
        allow_null=(
            masking is not None and masking.get("allow_null") is True
        ),
        require_finite=validation.get("finite") is True,
        exact_binary32=(
            validation.get("numeric_format") == "binary32"
            and validation.get("exact_round_trip") is True
        ),
        requires_residue_axis=definition.requires_residue_axis,
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
