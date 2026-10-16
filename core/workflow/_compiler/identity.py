"""Private Result Identity plan-fact compilation."""

from __future__ import annotations

from typing import Any, cast

from core.catalog.declarations import (
    ExecutionBindingDefinition,
    NodeTypeDefinition,
)
from core.catalog.model import FrozenCatalog, result_identity_contract
from core.workflow.plan import ResultIdentityPlanFacts
from datatypes.exact_reference import ExactContractReference


def _identity_without_digest(contract: Any) -> dict[str, str]:
    return {
        "contract_kind": contract.contract_kind,
        "contract_id": contract.contract_id,
    }

def _result_contracts_for_node(
    *,
    node_contract: Any,
    binding_contract: Any,
    catalog: FrozenCatalog,
    parameter_dependencies: tuple[ExactContractReference, ...] = (),
) -> tuple[Any, ...]:
    binding_definition = cast(
        ExecutionBindingDefinition,
        binding_contract.definition,
    )
    keys = {
        (node_contract.contract_kind, node_contract.contract_id),
        (binding_contract.contract_kind, binding_contract.contract_id),
        binding_definition.method.key,
    }
    keys.update(
        observation.metric.key
        for observation in binding_definition.produced_observations
    )
    roots = tuple(ExactContractReference(*key) for key in sorted(keys)) + parameter_dependencies
    return tuple(catalog.require_contract(*reference.key) for reference in catalog.resolve_contract_closure(roots))

def _result_identity_plan_facts(
    *,
    node_contract: Any,
    binding_contract: Any,
    method_contract: Any,
    result_contracts: tuple[Any, ...],
) -> ResultIdentityPlanFacts:
    node_definition = cast(
        NodeTypeDefinition,
        node_contract.definition,
    )
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
    return ResultIdentityPlanFacts(identity_facts=facts)
