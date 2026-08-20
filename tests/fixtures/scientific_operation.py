"""Public-interface constructors for direct Scientific Operation tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core import (
    AdmittedPort,
    AdmittedValue,
    FrozenCatalog,
    ObservationSelector,
    OperationCall,
    OperationContext,
    ResolvedProducedObservation,
    SelectionObjective,
)
from core.value_admission import admitted_port_values
from core.scoring_v2 import (
    resolve_observation_selector_facts,
    resolve_selection_objective_facts,
)
from datatypes import (
    CandidateDataReference,
    ExactContractReference,
    ResidueAxisReference,
)


def _reference(value: Mapping[str, Any]) -> ExactContractReference:
    return ExactContractReference(
        contract_kind=value["contract_kind"],
        contract_id=value["contract_id"],
        contract_version=value["contract_version"],
        contract_digest=value["contract_digest"],
    )


def operation_context(
    catalog: FrozenCatalog,
    binding_id: str,
    resources: Any,
    *,
    binding_version: str = "2.1.0",
    environment: Mapping[str, Any] | None = None,
    selection_objectives: Sequence[SelectionObjective] = (),
    observation_selectors: Sequence[ObservationSelector] = (),
) -> OperationContext:
    """Resolve one exact Binding into the public factory input contract."""
    binding = catalog.require_contract(
        "binding",
        binding_id,
        binding_version,
    )
    descriptor = binding.descriptor
    produced_observations = tuple(
        ResolvedProducedObservation(
            output_port=declaration["output_port"],
            output_partition=declaration["output_partition"],
            metric=_reference(declaration["metric"]),
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
        for declaration in descriptor.get("produced_observations", ())
    )

    return OperationContext(
        method=_reference(descriptor["method"]),
        produced_observations=produced_observations,
        selection_objectives=tuple(
            resolve_selection_objective_facts(objective, catalog)
            for objective in selection_objectives
        ),
        observation_selectors=tuple(
            resolve_observation_selector_facts(selector, catalog)
            for selector in observation_selectors
        ),
        environment={} if environment is None else environment,
        resources=resources,
    )


def operation_call(
    *,
    catalog: FrozenCatalog | None = None,
    binding_id: str | None = None,
    binding_version: str = "2.1.0",
    inputs: Mapping[str, Any] | None = None,
    node_parameters: Mapping[str, Any] | None = None,
    binding_parameters: Mapping[str, Any] | None = None,
) -> OperationCall:
    """Construct the exact immutable call admitted by the runtime boundary."""
    supplied_inputs = {} if inputs is None else inputs
    admitted_inputs = {}
    if supplied_inputs:
        if catalog is None or binding_id is None:
            raise AssertionError(
                "non-empty direct calls require an exact Catalog Binding"
            )
        binding = catalog.require_contract(
            "binding",
            binding_id,
            binding_version,
        )
        node_reference = binding.descriptor["node_type"]
        node_type = catalog.require_contract(
            node_reference["contract_kind"],
            node_reference["contract_id"],
            node_reference["contract_version"],
        )
        declarations = {
            declaration["name"]: declaration
            for declaration in node_type.descriptor.get("inputs", ())
        }
        candidate_data_port_types = {
            definition.type_id: definition
            for definition in catalog.port_types
        }
        for port_name, supplied in supplied_inputs.items():
            declaration = declarations[port_name]
            port_reference = declaration["port_type"]
            port_type = catalog.require_port_type(
                port_reference["contract_id"],
                port_reference["contract_version"],
            )
            values = (
                tuple(supplied)
                if declaration["multiplicity"] == "many"
                else (supplied,)
            )

            admitted_inputs[port_name] = admitted_port_values(
                port_type=port_type,
                multiplicity=declaration["multiplicity"],
                values=values,
                candidate_data_port_types=candidate_data_port_types,
            )
    return OperationCall(
        inputs=admitted_inputs,
        node_parameters={} if node_parameters is None else node_parameters,
        binding_parameters=(
            {} if binding_parameters is None else binding_parameters
        ),
    )


def admitted_port_fixture(
    value: Any,
    *,
    port_type_id: str,
    value_content_digests: tuple[str, ...],
    candidate_data: tuple[CandidateDataReference, ...] = (),
    scientific_axes: tuple[ResidueAxisReference, ...] = (),
    observation_methods: tuple[ExactContractReference, ...] = (),
    multiplicity: str = "one",
) -> AdmittedPort:
    """Build an explicitly pre-admitted record for operation boundary tests."""
    values = tuple(value) if multiplicity == "many" else (value,)
    if len(values) != len(value_content_digests):
        raise AssertionError(
            "pre-admitted fixture values and content digests must align"
        )
    admitted_values = tuple(
        AdmittedValue(
            value=item,
            canonical_bytes=("fixture:" + digest).encode("ascii"),
            content_digest=digest,
            candidate_data=candidate_data if index == 0 else (),
            scientific_axes=scientific_axes if index == 0 else (),
            observation_methods=(
                observation_methods if index == 0 else ()
            ),
        )
        for index, (item, digest) in enumerate(
            zip(values, value_content_digests, strict=True)
        )
    )
    return AdmittedPort(
        port_type={
            "contract_kind": "port_type",
            "contract_id": port_type_id,
            "contract_version": "fixture",
            "contract_digest": "sha256:" + ("0" * 64),
        },
        multiplicity=multiplicity,
        values=admitted_values,
        content_digest=(
            admitted_values[0].content_digest
            if len(admitted_values) == 1
            else "sha256:" + ("f" * 64)
        ),
    )


def build_operation(
    catalog: FrozenCatalog,
    binding_id: str,
    resources: Any,
    *,
    binding_version: str = "2.1.0",
    environment: Mapping[str, Any] | None = None,
    selection_objectives: Sequence[SelectionObjective] = (),
    observation_selectors: Sequence[ObservationSelector] = (),
) -> Any:
    """Build an operation through the Catalog's public factory Interface."""
    context = operation_context(
        catalog,
        binding_id,
        resources,
        binding_version=binding_version,
        environment=environment,
        selection_objectives=selection_objectives,
        observation_selectors=observation_selectors,
    )
    return catalog.require_factory(binding_id, binding_version).build(context)
