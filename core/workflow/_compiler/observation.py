"""Private typed Observation Plan compilation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.scoring.observation_plan import (
    ObservationPlanError,
    ObservationPropagationFilter,
    ObservationPropagationPlan,
    ProducedObservationPlan,
    ResolvedProducedObservation,
    resolve_metric_facts,
)
from core.workflow.compiler import WorkflowCompileError
from datatypes.exact_reference import ExactContractReference


def _contract_descriptor(contract: Any) -> Mapping[str, Any]:
    descriptor = contract.descriptor
    return descriptor() if callable(descriptor) else descriptor

def _resolved_produced_observations(
    binding_contract: Any,
) -> tuple[ResolvedProducedObservation, ...]:
    return tuple(
        ResolvedProducedObservation(
            output_port=declaration["output_port"],
            output_partition=declaration["output_partition"],
            metric=ExactContractReference(**declaration["metric"]),
            context_profile=declaration["context_profile"],
            subject_grain=declaration["subject_grain"],
            source_role=declaration["source_role"],
            subject_direction=declaration["subject_direction"],
            subject_port=declaration["subject_port"],
            guaranteed_multiplicity=declaration[
                "guaranteed_multiplicity"
            ],
            reference_direction=declaration.get("reference_direction"),
            reference_port=declaration.get("reference_port"),
            pairing_direction=declaration.get("pairing_direction"),
            pairing_port=declaration.get("pairing_port"),
            axis_direction=declaration.get("axis_direction"),
            axis_port=declaration.get("axis_port"),
            method_direction=declaration.get("method_direction"),
            method_port=declaration.get("method_port"),
        )
        for declaration in binding_contract.descriptor.get(
            "produced_observations",
            (),
        )
    )

def _resolved_observation_propagation(
    binding_contract: Any,
) -> ObservationPropagationPlan | None:
    descriptor = binding_contract.descriptor.get("observation_propagation")
    if descriptor is None:
        return None
    filter_descriptor = descriptor.get("filter")
    propagation_filter = (
        None
        if filter_descriptor is None
        else ObservationPropagationFilter(
            source_partition=filter_descriptor.get("source_partition"),
            metric=(
                ExactContractReference(**filter_descriptor["metric"])
                if filter_descriptor.get("metric") is not None
                else None
            ),
            method=(
                ExactContractReference(**filter_descriptor["method"])
                if filter_descriptor.get("method") is not None
                else None
            ),
            context_profile=filter_descriptor.get("context_profile"),
        )
    )
    return ObservationPropagationPlan(
        mode=descriptor["mode"],
        output_port=descriptor["output_port"],
        input_ports=tuple(descriptor["input_ports"]),
        filter=propagation_filter,
        absent_input_policy=descriptor.get("absent_input_policy", "reject"),
    )

def _resolved_produced_observation_plan(
    binding_contract: Any,
    *,
    resolved_by_key: Mapping[tuple[str, str, str], Any],
    node_id: str,
) -> ProducedObservationPlan:
    observations = _resolved_produced_observations(binding_contract)
    metric_facts = {}
    try:
        for observation in observations:
            metric = resolved_by_key[
                (
                    observation.metric.contract_kind,
                    observation.metric.contract_id,
                    observation.metric.contract_version,
                )
            ]
            if metric.contract_digest != observation.metric.contract_digest:
                raise ObservationPlanError(
                    "Produced Observation Metric digest is not exact"
                )
            metric_facts[observation.metric] = resolve_metric_facts(
                observation.metric,
                metric.descriptor,
            )
        return ProducedObservationPlan(
            binding_method=ExactContractReference(
                **binding_contract.descriptor["method"]
            ),
            observations=observations,
            metric_facts=metric_facts,
            propagation=_resolved_observation_propagation(binding_contract),
        )
    except (KeyError, ObservationPlanError) as error:
        raise WorkflowCompileError(
            "invalid_produced_observation_plan",
            str(error),
            node_id=node_id,
        ) from error
