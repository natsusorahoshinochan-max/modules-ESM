"""Public-interface constructors for direct Scientific Operation tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core import (
    FrozenCatalog,
    InputContentDigests,
    ObservationSelector,
    OperationCall,
    OperationContext,
    ResolvedProducedObservation,
    SelectionObjective,
)
from core.scoring_v2 import (
    resolve_observation_selector_facts,
    resolve_selection_objective_facts,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    ProteinSequence,
    ProteinStructure,
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
    admitted_digests: dict[str, InputContentDigests] = {}
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
            candidate_digests: list[CandidateDataReference] = []
            for value in values:
                if type(value) is Candidate:
                    candidates = (value,)
                elif type(value) is CandidateCollection:
                    candidates = tuple(value.items)
                else:
                    candidates = ()
                for candidate in candidates:
                    data_type_id = {
                        ProteinSequence: "protein.sequence",
                        ProteinStructure: "protein.structure",
                    }.get(type(candidate.data))
                    if data_type_id is None:
                        raise AssertionError(
                            "Candidate data has no active test content identity"
                        )
                    data_types = tuple(
                        candidate_data_type
                        for candidate_data_type in catalog.port_types
                        if candidate_data_type.type_id == data_type_id
                    )
                    if len(data_types) != 1:
                        raise AssertionError(
                            f"active Port Type {data_type_id!r} did not "
                            "resolve exactly once"
                        )
                    candidate_digests.append(
                        CandidateDataReference(
                            candidate_id=candidate.candidate_id,
                            data_type_id=data_type_id,
                            content_digest=data_types[0].content_digest(
                                candidate.data
                            ),
                        )
                    )
            admitted_digests[port_name] = InputContentDigests(
                port_type_id=port_type.type_id,
                value_content_digests=tuple(
                    port_type.content_digest(value) for value in values
                ),
                candidate_data=tuple(candidate_digests),
            )
    return OperationCall(
        inputs=supplied_inputs,
        node_parameters={} if node_parameters is None else node_parameters,
        binding_parameters=(
            {} if binding_parameters is None else binding_parameters
        ),
        input_content_digests=admitted_digests,
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
