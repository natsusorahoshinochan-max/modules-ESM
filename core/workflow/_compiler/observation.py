"""Private typed Observation Plan compilation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from core.catalog.declarations import (
    ExecutionBindingDefinition,
    MetricDefinition,
    ObservationPropagationDefinition,
)
from core.scoring.observation_plan import (
    CalibrationContextProfile,
    IntrinsicContextProfile,
    ObservationContextProfile,
    ObservationPropagationFilter,
    ObservationPropagationPlan,
    PairwiseContextProfile,
    ProducedObservationPlan,
    ResolvedProducedObservation,
    resolve_metric_facts,
)
from datatypes.exact_reference import ExactContractReference


def _resolved_reference(contract: Any) -> ExactContractReference:
    return ExactContractReference(**contract.reference())


def _resolved_context_profile(
    profile: Mapping[str, Any],
) -> ObservationContextProfile:
    """Translate one Catalog-admitted profile without admitting it again."""
    kind = profile["kind"]
    if kind == "intrinsic":
        return IntrinsicContextProfile()
    if kind == "calibration":
        return CalibrationContextProfile(
            calibration_metric=profile["calibration_metric"],
            calibration_value=profile["calibration_value"],
            calibration_unit=profile["calibration_unit"],
            population_id=profile["population_id"],
        )
    return PairwiseContextProfile(
        subject_role=profile["subject_role"],
        reference_role=profile["reference_role"],
        pairing_mode=profile["pairing_mode"],
        normalization=profile["normalization"],
    )

def _resolved_produced_observations(
    binding: ExecutionBindingDefinition,
    resolved_by_key: Mapping[tuple[str, str, str], Any],
) -> tuple[ResolvedProducedObservation, ...]:
    return tuple(
        ResolvedProducedObservation(
            output_port=declaration.output_port,
            output_partition=declaration.output_partition,
            metric=_resolved_reference(
                resolved_by_key[declaration.metric.key]
            ),
            context_profile=_resolved_context_profile(
                declaration.context_profile
            ),
            subject_grain=declaration.subject_grain,
            source_role=declaration.source_role,
            subject_direction=declaration.subject_direction,
            subject_port=declaration.subject_port,
            guaranteed_multiplicity=declaration.guaranteed_multiplicity,
            reference_direction=declaration.reference_direction,
            reference_port=declaration.reference_port,
            pairing_direction=declaration.pairing_direction,
            pairing_port=declaration.pairing_port,
            axis_direction=declaration.axis_direction,
            axis_port=declaration.axis_port,
            method_direction=declaration.method_direction,
            method_port=declaration.method_port,
        )
        for declaration in binding.produced_observations
    )

def _resolved_observation_propagation(
    propagation: ObservationPropagationDefinition | None,
    resolved_by_key: Mapping[tuple[str, str, str], Any],
) -> ObservationPropagationPlan | None:
    if propagation is None:
        return None
    filter_definition = propagation.filter
    propagation_filter = (
        None
        if filter_definition is None
        else ObservationPropagationFilter(
            source_partition=filter_definition.get("source_partition"),
            metric=(
                _resolved_reference(
                    resolved_by_key[filter_definition["metric"].key]
                )
                if filter_definition.get("metric") is not None
                else None
            ),
            method=(
                _resolved_reference(
                    resolved_by_key[filter_definition["method"].key]
                )
                if filter_definition.get("method") is not None
                else None
            ),
            context_profile=(
                _resolved_context_profile(filter_definition["context_profile"])
                if filter_definition.get("context_profile") is not None
                else None
            ),
        )
    )
    return ObservationPropagationPlan(
        mode=propagation.mode,
        output_port=propagation.output_port,
        input_ports=propagation.input_ports,
        filter=propagation_filter,
        absent_input_policy=propagation.absent_input_policy,
    )

def _resolved_produced_observation_plan(
    binding_contract: Any,
    *,
    resolved_by_key: Mapping[tuple[str, str, str], Any],
) -> ProducedObservationPlan:
    binding = cast(ExecutionBindingDefinition, binding_contract.definition)
    observations = _resolved_produced_observations(
        binding,
        resolved_by_key,
    )
    metric_facts = {}
    for observation in observations:
        metric = resolved_by_key[observation.metric.key]
        metric_facts[observation.metric] = resolve_metric_facts(
            observation.metric,
            cast(MetricDefinition, metric.definition),
        )
    return ProducedObservationPlan(
        binding_method=_resolved_reference(
            resolved_by_key[binding.method.key]
        ),
        observations=observations,
        metric_facts=metric_facts,
        propagation=_resolved_observation_propagation(
            binding.observation_propagation,
            resolved_by_key,
        ),
    )
