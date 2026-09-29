"""Derive Metric facts while retaining admitted Observation contracts."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from core.catalog.declarations import ExecutionBindingDefinition, MetricDefinition
from core.scoring.observation_plan import ProducedObservationPlan, resolve_metric_facts

if TYPE_CHECKING:
    from core.catalog.model import CatalogContract, FrozenCatalog


def produced_observation_plan(
    binding_contract: CatalogContract,
    *,
    catalog: FrozenCatalog,
) -> ProducedObservationPlan:
    binding = cast(ExecutionBindingDefinition, binding_contract.definition)
    metric_facts = {}
    for observation in binding.produced_observations:
        metric = catalog.require_contract(*observation.metric.key)
        metric_facts[observation.metric] = resolve_metric_facts(
            observation.metric, cast(MetricDefinition, metric.definition),
        )
    return ProducedObservationPlan(
        binding_method=binding.method,
        observations=binding.produced_observations,
        metric_facts=MappingProxyType(metric_facts),
        propagation=binding.observation_propagation,
    )
