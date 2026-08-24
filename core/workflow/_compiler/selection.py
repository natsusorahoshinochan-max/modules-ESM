"""Private typed Selection plan compilation."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, cast

from core.catalog.declarations import UtilityTransformDefinition
from core.parameters.model import AdmittedParameterValues
from core.scoring.selection import (
    ObservationSelector,
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
    ResolvedUtilityTransform,
    SelectionObjective,
    UtilityParameterFacts,
    context_selector_canonical,
)
from core.workflow.errors import WorkflowCompileError
from datatypes.exact_reference import ExactContractReference


def _resolved_reference(contract: Any) -> ExactContractReference:
    return ExactContractReference(**contract.reference())

def _compile_selection_objective(
    objective: SelectionObjective,
    utility_parameters: AdmittedParameterValues,
    effective_weight: float,
    *,
    resolved_by_key: Mapping[tuple[str, str, str], Any],
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
    utility_definition = cast(
        UtilityTransformDefinition,
        utility.definition,
    )
    compatible = utility_definition.compatible_input_contract
    if (
        compatible["metric"].key != objective.metric.key
        or compatible["method"].key != objective.method.key
        or compatible["context_profile"]
        != context_selector_canonical(objective.context_selector)
    ):
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
            parameters=UtilityParameterFacts(utility_parameters),
            apply=utility_definition.transform,
        ),
        declared_weight=objective.weight,
        effective_weight=effective_weight,
        match_cardinality=objective.match_cardinality,
        missing_policy=objective.missing_policy,
    )


def _compile_selection_objectives(
    objectives: tuple[SelectionObjective, ...],
    *,
    compilation_by_id: Mapping[
        str,
        tuple[int, AdmittedParameterValues],
    ],
    resolved_by_key: Mapping[tuple[str, str, str], Any],
) -> tuple[ResolvedSelectionObjective, ...]:
    if not objectives:
        return ()
    try:
        declared_total = math.fsum(item.weight for item in objectives)
    except OverflowError:
        declared_total = math.inf
    if not math.isfinite(declared_total) or declared_total <= 0:
        raise WorkflowCompileError(
            "invalid_selection_objective",
            "Selected Selection Objectives require a finite positive total "
            "weight",
            field_path=("selection_objectives",),
        )
    return tuple(
        _compile_selection_objective(
            objective,
            compilation_by_id[objective.objective_id][1],
            objective.weight / declared_total,
            resolved_by_key=resolved_by_key,
            objective_index=compilation_by_id[objective.objective_id][0],
        )
        for objective in objectives
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
