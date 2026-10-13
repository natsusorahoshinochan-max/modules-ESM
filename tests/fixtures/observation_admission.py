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
from tests.support.output_admission import admit_fixture_port
from datatypes.observation import ScoreCollection


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
        plan=catalog.produced_observation_plan(binding.contract_id),
        output_port=output_port,
        collection=collection,
        inputs=admitted_inputs,
        outputs=admitted_outputs,
    )
