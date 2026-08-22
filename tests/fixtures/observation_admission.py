"""Test constructors around the typed Produced Observation admission seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from core.operation import AdmittedPort
from core.catalog.model import (
    FrozenCatalog,
)
from core.scoring.observation_admission import (
    ObservationAdmissionError,
    admit_produced_observations,
)
from core.scoring.observation_plan import (
    ObservationPropagationFilter,
    ObservationPropagationPlan,
    ProducedObservationPlan,
    ResolvedProducedObservation,
    resolve_metric_facts,
)
from tests.support.output_admission import admit_fixture_port
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import ScoreCollection


def _resolved_observations(binding: Any) -> tuple[ResolvedProducedObservation, ...]:
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
            guaranteed_multiplicity=declaration["guaranteed_multiplicity"],
            reference_direction=declaration.get("reference_direction"),
            reference_port=declaration.get("reference_port"),
            pairing_direction=declaration.get("pairing_direction"),
            pairing_port=declaration.get("pairing_port"),
            axis_direction=declaration.get("axis_direction"),
            axis_port=declaration.get("axis_port"),
            method_direction=declaration.get("method_direction"),
            method_port=declaration.get("method_port"),
        )
        for declaration in binding.descriptor.get("produced_observations", ())
    )


def _resolved_propagation(binding: Any) -> ObservationPropagationPlan | None:
    descriptor = binding.descriptor.get("observation_propagation")
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


def compiled_observation_plan_for_test(
    catalog: FrozenCatalog,
    binding: Any,
) -> ProducedObservationPlan:
    """Build the same typed facts a real Workflow Compiler supplies."""
    observations = _resolved_observations(binding)
    metric_facts = {}
    for observation in observations:
        metric = catalog.require_contract(
            observation.metric.contract_kind,
            observation.metric.contract_id,
            observation.metric.contract_version,
        )
        if metric.contract_digest != observation.metric.contract_digest:
            raise ObservationAdmissionError(
                "Produced Observation Metric digest is not exact"
            )
        metric_facts[observation.metric] = resolve_metric_facts(
            observation.metric,
            metric.definition,
        )
    return ProducedObservationPlan(
        binding_method=ExactContractReference(**binding.descriptor["method"]),
        observations=observations,
        metric_facts=metric_facts,
        propagation=_resolved_propagation(binding),
    )


def _admit_test_ports(
    *,
    catalog: FrozenCatalog,
    declarations: Sequence[Mapping[str, Any]],
    supplied_values: Mapping[str, Any],
) -> Mapping[str, AdmittedPort]:
    declarations_by_name = {
        declaration["name"]: declaration for declaration in declarations
    }
    unknown = set(supplied_values) - set(declarations_by_name)
    if unknown:
        raise ObservationAdmissionError(
            f"Score test received unknown Ports: {sorted(unknown)!r}"
        )
    candidate_data_port_types = {
        definition.type_id: definition for definition in catalog.port_types
    }
    admitted = {}
    for port_name, raw_value in supplied_values.items():
        declaration = declarations_by_name[port_name]
        reference = declaration["port_type"]
        port_type = catalog.require_port_type(
            reference["contract_id"],
            reference["contract_version"],
        )
        if port_type.reference() != dict(reference):
            raise ObservationAdmissionError(
                "Score test Port Type identity is not exact"
            )
        values = (
            tuple(raw_value)
            if declaration["multiplicity"] == "many"
            else (raw_value,)
        )
        admitted[port_name] = admit_fixture_port(
            port_type=port_type,
            multiplicity=declaration["multiplicity"],
            values=values,
            candidate_data_port_types=candidate_data_port_types,
        )
    return MappingProxyType(admitted)


def admit_test_produced_score_collection(
    *,
    catalog: FrozenCatalog,
    binding: Any,
    output_port: str,
    collection: ScoreCollection,
    inputs: Mapping[str, Any],
    outputs: Mapping[str, Any],
) -> None:
    """Exercise Observation Admission with test-admitted Port values."""
    node_reference = binding.descriptor["node_type"]
    node_type = catalog.require_contract(
        node_reference["contract_kind"],
        node_reference["contract_id"],
        node_reference["contract_version"],
    )
    admitted_inputs = _admit_test_ports(
        catalog=catalog,
        declarations=node_type.descriptor.get("inputs", ()),
        supplied_values=inputs,
    )
    supplied_outputs = dict(outputs)
    supplied_outputs[output_port] = collection
    admitted_outputs = _admit_test_ports(
        catalog=catalog,
        declarations=node_type.descriptor.get("outputs", ()),
        supplied_values=supplied_outputs,
    )
    admit_produced_observations(
        plan=compiled_observation_plan_for_test(catalog, binding),
        output_port=output_port,
        collection=collection,
        inputs=admitted_inputs,
        outputs=admitted_outputs,
    )
