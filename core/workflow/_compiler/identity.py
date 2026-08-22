"""Private Result Identity plan-fact compilation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.catalog.model import FrozenCatalog
from core.catalog.port_contract import ContractResolutionError
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
from core.workflow._compiler.observation import _contract_descriptor
from core.workflow.compiler import WorkflowCompileError
from core.workflow.plan import ResultIdentityPlanFacts


_PRESENTATION_CONTRACT_FIELDS = {
    "node_type": frozenset({"title", "summary", "category"}),
    "metric": frozenset({"title", "description"}),
}


def _identity_without_digest(reference: Mapping[str, Any]) -> dict[str, str]:
    return {
        "contract_kind": reference["contract_kind"],
        "contract_id": reference["contract_id"],
        "contract_version": reference["contract_version"],
    }

def _normalize_nested_contract_references(value: Any) -> Any:
    if isinstance(value, Mapping):
        fields = set(value)
        is_contract_reference = fields == {
            "contract_kind",
            "contract_id",
            "contract_version",
            "contract_digest",
        }
        return {
            str(key): _normalize_nested_contract_references(item)
            for key, item in value.items()
            if not (is_contract_reference and key == "contract_digest")
        }
    if isinstance(value, (list, tuple)):
        return [
            _normalize_nested_contract_references(item)
            for item in value
        ]
    return value

def _result_affecting_contract(contract: Any) -> dict[str, Any]:
    descriptor = _contract_descriptor(contract)
    contract_kind = descriptor["contract_kind"]
    presentation_fields = _PRESENTATION_CONTRACT_FIELDS.get(
        contract_kind,
        (),
    )
    return {
        "contract_kind": contract_kind,
        "contract_id": descriptor["contract_id"],
        "contract_version": descriptor["contract_version"],
        "descriptor": _normalize_nested_contract_references(
            {
                key: value
                for key, value in descriptor.items()
                if key not in presentation_fields
            }
        ),
    }

def _result_contracts_for_node(
    *,
    node_contract: Any,
    binding_contract: Any,
    selected_objectives: tuple[SelectionObjective, ...],
    selected_selectors: tuple[ObservationSelector, ...],
    catalog: FrozenCatalog,
    resolved_by_key: Mapping[tuple[str, str, str], Any],
) -> tuple[Any, ...]:
    keys = {
        (
            node_contract.contract_kind,
            node_contract.contract_id,
            node_contract.contract_version,
        ),
        (
            binding_contract.contract_kind,
            binding_contract.contract_id,
            binding_contract.contract_version,
        ),
    }
    for objective in selected_objectives:
        keys.update(
            (
                reference.contract_kind,
                reference.contract_id,
                reference.contract_version,
            )
            for reference in (
                objective.metric,
                objective.method,
                objective.utility_transform,
            )
        )
    for selector in selected_selectors:
        keys.update(
            (
                reference.contract_kind,
                reference.contract_id,
                reference.contract_version,
            )
            for reference in (selector.metric, selector.method)
        )
    try:
        references = catalog.resolve_contract_closure(
            tuple(catalog.require_reference(*key) for key in sorted(keys))
        )
        return tuple(resolved_by_key[reference.key] for reference in references)
    except (ContractResolutionError, KeyError) as error:
        raise WorkflowCompileError(
            "contract_lock_mismatch",
            "Execution Plan result contract is outside the exact Lock",
        ) from error

def _result_identity_plan_facts(
    *,
    node_contract: Any,
    binding_contract: Any,
    method_contract: Any,
    result_contracts: tuple[Any, ...],
    selected_objectives: tuple[ResolvedSelectionObjective, ...],
    selected_selectors: tuple[ResolvedObservationSelector, ...],
) -> ResultIdentityPlanFacts:
    objective_consumption = binding_contract.descriptor.get(
        "selection_objective_consumption"
    )
    selector_consumption = binding_contract.descriptor.get(
        "observation_selector_consumption"
    )
    facts: dict[str, Any] = {
        "node_type": _identity_without_digest(node_contract.reference()),
        "binding": _identity_without_digest(binding_contract.reference()),
        "method": _identity_without_digest(method_contract.reference()),
        "resolved_result_contracts": [
            _result_affecting_contract(contract)
            for contract in result_contracts
        ],
        "input_contracts": [
            {
                "input_port": port["name"],
                "port_type": _identity_without_digest(port["port_type"]),
                "required": port["required"],
                "multiplicity": port["multiplicity"],
                "scientific_meaning": port["scientific_meaning"],
            }
            for port in node_contract.descriptor.get("inputs", ())
        ],
        "output_contracts": [
            {
                "output_port": port["name"],
                "port_type": _identity_without_digest(port["port_type"]),
                "required": port["required"],
                "multiplicity": port["multiplicity"],
                "scientific_meaning": port["scientific_meaning"],
            }
            for port in node_contract.descriptor.get("outputs", ())
        ],
        "produced_observations": _normalize_nested_contract_references(
            binding_contract.descriptor.get("produced_observations", ())
        ),
    }
    node_parameter_indirections: list[str] = []
    if selected_objectives:
        if not isinstance(objective_consumption, Mapping):
            raise WorkflowCompileError(
                "invalid_selection_objective_consumer",
                "Selection Objective facts lack exact local input roles",
            )
        candidate_input_port = objective_consumption.get(
            "candidate_input_port"
        )
        score_collection_input_port = objective_consumption.get(
            "score_collection_input_port"
        )
        if not isinstance(candidate_input_port, str) or not isinstance(
            score_collection_input_port,
            str,
        ):
            raise WorkflowCompileError(
                "invalid_selection_objective_consumer",
                "Selection Objective facts lack exact local input roles",
            )
        facts["selection_objectives"] = [
            selection_objective_identity_canonical(fact)
            for fact in selection_objective_identity_facts_from_facts(
                selected_objectives,
                candidate_input_port=candidate_input_port,
                score_collection_input_port=score_collection_input_port,
            )
        ]
        node_parameter_indirections.extend(
            parameter
            for parameter in (
                objective_consumption.get("objective_id_parameter"),
                objective_consumption.get("objective_ids_parameter"),
            )
            if isinstance(parameter, str)
        )
    if selected_selectors:
        if not isinstance(selector_consumption, Mapping):
            raise WorkflowCompileError(
                "invalid_observation_selector_consumer",
                "Observation Selector facts lack exact local input roles",
            )
        candidate_input_port = selector_consumption.get(
            "candidate_input_port"
        )
        score_collection_input_port = selector_consumption.get(
            "score_collection_input_port"
        )
        if not isinstance(candidate_input_port, str) or not isinstance(
            score_collection_input_port,
            str,
        ):
            raise WorkflowCompileError(
                "invalid_observation_selector_consumer",
                "Observation Selector facts lack exact local input roles",
            )
        facts["observation_selectors"] = [
            observation_selector_identity_canonical(fact)
            for fact in observation_selector_identity_facts_from_facts(
                selected_selectors,
                candidate_input_port=candidate_input_port,
                score_collection_input_port=score_collection_input_port,
            )
        ]
        parameter = selector_consumption.get("selector_id_parameter")
        if isinstance(parameter, str):
            node_parameter_indirections.append(parameter)
    return ResultIdentityPlanFacts(
        identity_facts=facts,
        node_parameter_indirections=tuple(node_parameter_indirections),
    )
