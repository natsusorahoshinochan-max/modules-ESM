"""Private Result Identity plan-fact compilation."""

from __future__ import annotations

from typing import Any, cast

from core.catalog.declarations import (
    ExecutionBindingDefinition,
    NodeTypeDefinition,
)
from core.catalog.model import FrozenCatalog, result_identity_contract
from core.scoring.selection import (
    ObservationSelector,
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
    SelectionObjective,
    observation_selector_identity_canonical,
    observation_selector_identity_facts_from_facts,
    selection_objective_identity_canonical,
    selection_objective_identity_facts_from_facts,
)
from core.workflow.plan import ResultIdentityPlanFacts


def _identity_without_digest(contract: Any) -> dict[str, str]:
    return {
        "contract_kind": contract.contract_kind,
        "contract_id": contract.contract_id,
    }

def _result_contracts_for_node(
    *,
    node_contract: Any,
    binding_contract: Any,
    selected_objectives: tuple[SelectionObjective, ...],
    selected_selectors: tuple[ObservationSelector, ...],
    catalog: FrozenCatalog,
) -> tuple[Any, ...]:
    binding_definition = cast(
        ExecutionBindingDefinition,
        binding_contract.definition,
    )
    keys = {
        (node_contract.contract_kind, node_contract.contract_id),
        binding_definition.method.key,
    }
    keys.update(
        observation.metric.key
        for observation in binding_definition.produced_observations
    )
    for objective in selected_objectives:
        keys.update(
            reference.key
            for reference in (
                objective.metric,
                objective.method,
                objective.utility_transform,
            )
        )
    for selector in selected_selectors:
        keys.update(
            reference.key
            for reference in (selector.metric, selector.method)
        )
    return tuple(catalog.require_contract(*key) for key in sorted(keys))

def _result_identity_plan_facts(
    *,
    node_contract: Any,
    binding_contract: Any,
    method_contract: Any,
    result_contracts: tuple[Any, ...],
    selected_objectives: tuple[ResolvedSelectionObjective, ...],
    selected_selectors: tuple[ResolvedObservationSelector, ...],
) -> ResultIdentityPlanFacts:
    node_definition = cast(
        NodeTypeDefinition,
        node_contract.definition,
    )
    binding_definition = cast(
        ExecutionBindingDefinition,
        binding_contract.definition,
    )
    objective_consumption = binding_definition.selection_objective_consumption
    selector_consumption = binding_definition.observation_selector_consumption
    facts: dict[str, Any] = {
        "node_type": _identity_without_digest(node_contract),
        "binding": _identity_without_digest(binding_contract),
        "method": _identity_without_digest(method_contract),
        "resolved_result_contracts": [
            result_identity_contract(contract)
            for contract in result_contracts
        ],
        "input_contracts": [
            {
                "input_port": port.name,
                "port_type": {
                    "contract_kind": port.port_type.contract_kind,
                    "contract_id": port.port_type.contract_id,
                },
                "required": port.required,
                "multiplicity": port.multiplicity,
                "scientific_meaning": port.scientific_meaning,
            }
            for port in node_definition.inputs
        ],
        "output_contracts": [
            {
                "output_port": port.name,
                "port_type": {
                    "contract_kind": port.port_type.contract_kind,
                    "contract_id": port.port_type.contract_id,
                },
                "required": port.required,
                "multiplicity": port.multiplicity,
                "scientific_meaning": port.scientific_meaning,
            }
            for port in node_definition.outputs
        ],
        "produced_observations": binding_contract.result_identity_descriptor[
            "descriptor"
        ]["produced_observations"],
    }
    node_parameter_indirections: list[str] = []
    if selected_objectives:
        facts["selection_objectives"] = [
            selection_objective_identity_canonical(fact)
            for fact in selection_objective_identity_facts_from_facts(
                selected_objectives,
                candidate_input_port=objective_consumption.candidate_input_port,
                score_collection_input_port=(
                    objective_consumption.score_collection_input_port
                ),
            )
        ]
        node_parameter_indirections.extend(
            parameter
            for parameter in (
                objective_consumption.objective_id_parameter,
                objective_consumption.objective_ids_parameter,
            )
            if parameter is not None
        )
    if selected_selectors:
        facts["observation_selectors"] = [
            observation_selector_identity_canonical(fact)
            for fact in observation_selector_identity_facts_from_facts(
                selected_selectors,
                candidate_input_port=selector_consumption.candidate_input_port,
                score_collection_input_port=(
                    selector_consumption.score_collection_input_port
                ),
            )
        ]
        node_parameter_indirections.append(
            selector_consumption.selector_id_parameter
        )
    return ResultIdentityPlanFacts(
        identity_facts=facts,
        node_parameter_indirections=tuple(node_parameter_indirections),
    )
