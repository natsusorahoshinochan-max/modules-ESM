"""Private typed Selection plan compilation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.catalog.model import FrozenCatalog
from core.parameters.model import AdmittedParameterValues
from core.scoring.selection import (
    ObservationSelector,
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
    ResolvedUtilityTransform,
    SelectionObjective,
    context_selector_canonical,
)
from core.workflow.compiler import WorkflowCompileError
from core.workflow.document import WorkflowDocument
from datatypes.exact_reference import ExactContractReference


def _selected_objectives(
    workflow: WorkflowDocument,
    *,
    node_id: str,
    node_parameters: Mapping[str, Any],
    binding_contract: Any,
) -> tuple[SelectionObjective, ...]:
    consumption = binding_contract.descriptor.get(
        "selection_objective_consumption"
    )
    if not isinstance(consumption, Mapping):
        return ()
    scalar_parameter = consumption.get("objective_id_parameter")
    ordered_parameter = consumption.get("objective_ids_parameter")
    if isinstance(scalar_parameter, str):
        objective_ids = (node_parameters.get(scalar_parameter),)
    elif isinstance(ordered_parameter, str):
        raw_ids = node_parameters.get(ordered_parameter)
        objective_ids = (
            tuple(raw_ids) if isinstance(raw_ids, (list, tuple)) else ()
        )
    else:
        objective_ids = ()
    objectives = {
        objective.objective_id: objective
        for objective in workflow.selection_objectives
    }
    if (
        not objective_ids
        or any(not isinstance(item, str) for item in objective_ids)
        or any(item not in objectives for item in objective_ids)
    ):
        raise WorkflowCompileError(
            "invalid_selection_objective_consumer",
            "Selection Objective consumption did not resolve during compilation",
            node_id=node_id,
        )
    return tuple(objectives[item] for item in objective_ids)

def _selected_observation_selectors(
    workflow: WorkflowDocument,
    *,
    node_id: str,
    node_parameters: Mapping[str, Any],
    binding_contract: Any,
) -> tuple[ObservationSelector, ...]:
    consumption = binding_contract.descriptor.get(
        "observation_selector_consumption"
    )
    if not isinstance(consumption, Mapping):
        return ()
    parameter = consumption.get("selector_id_parameter")
    selector_id = (
        node_parameters.get(parameter)
        if isinstance(parameter, str)
        else None
    )
    selectors = {
        selector.selector_id: selector
        for selector in workflow.observation_selectors
    }
    if not isinstance(selector_id, str) or selector_id not in selectors:
        raise WorkflowCompileError(
            "invalid_observation_selector_consumer",
            "Observation Selector consumption did not resolve during compilation",
            node_id=node_id,
        )
    return (selectors[selector_id],)

def _resolved_reference(contract: Any) -> ExactContractReference:
    return ExactContractReference(**contract.reference())

def _compile_selection_objective(
    objective: SelectionObjective,
    utility_parameters: AdmittedParameterValues,
    *,
    resolved_by_key: Mapping[tuple[str, str, str], Any],
    catalog: FrozenCatalog,
    objective_index: int,
) -> ResolvedSelectionObjective:
    metric = resolved_by_key[
        (
            objective.metric.contract_kind,
            objective.metric.contract_id,
            objective.metric.contract_version,
        )
    ]
    method = resolved_by_key[
        (
            objective.method.contract_kind,
            objective.method.contract_id,
            objective.method.contract_version,
        )
    ]
    utility = resolved_by_key[
        (
            objective.utility_transform.contract_kind,
            objective.utility_transform.contract_id,
            objective.utility_transform.contract_version,
        )
    ]
    compatible = utility.descriptor["compatible_input_contract"]
    expected = {
        "metric": metric.reference(),
        "method": method.reference(),
        "context_profile": context_selector_canonical(
            objective.context_selector
        ),
    }
    if any(compatible[name] != value for name, value in expected.items()):
        raise WorkflowCompileError(
            "invalid_selection_objective",
            "Utility Transform is incompatible with the exact Metric, "
            "Method, or Context",
            field_path=("selection_objectives", objective_index),
        )
    return ResolvedSelectionObjective(
        objective_id=objective.objective_id,
        candidate_input=objective.candidate_input,
        score_collection_input=objective.score_collection_input,
        source_partition=objective.source_partition,
        metric=_resolved_reference(metric),
        method=_resolved_reference(method),
        context_selector=objective.context_selector,
        utility=ResolvedUtilityTransform(
            reference=_resolved_reference(utility),
            parameters=utility_parameters,
            apply=catalog.require_utility_transform(
                utility.contract_id,
                utility.contract_version,
            ),
        ),
        weight=objective.weight,
        match_cardinality=objective.match_cardinality,
        missing_policy=objective.missing_policy,
    )

def _compile_observation_selector(
    selector: ObservationSelector,
    *,
    resolved_by_key: Mapping[tuple[str, str, str], Any],
) -> ResolvedObservationSelector:
    metric = resolved_by_key[
        (
            selector.metric.contract_kind,
            selector.metric.contract_id,
            selector.metric.contract_version,
        )
    ]
    method = resolved_by_key[
        (
            selector.method.contract_kind,
            selector.method.contract_id,
            selector.method.contract_version,
        )
    ]
    return ResolvedObservationSelector(
        selector_id=selector.selector_id,
        candidate_input=selector.candidate_input,
        score_collection_input=selector.score_collection_input,
        source_partition=selector.source_partition,
        metric=_resolved_reference(metric),
        method=_resolved_reference(method),
        context_selector=selector.context_selector,
        match_cardinality=selector.match_cardinality,
        missing_policy=selector.missing_policy,
    )
