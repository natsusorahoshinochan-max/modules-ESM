"""Public mapping codec for typed Selection values and provenance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.scoring.selection import (
    ContextSelector,
    ObservationSelector,
    ObservationSelectorProvenance,
    PairwiseContextSelector,
    SelectionInput,
    SelectionObjective,
    SelectionObjectiveProvenance,
    SelectionProvenance,
)
from datatypes.exact_reference import ExactContractReference
from datatypes.i_json import thaw_i_json
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
)


def selection_input_from_public(value: Mapping[str, Any]) -> SelectionInput:
    return SelectionInput(
        node_id=value["node_id"],
        output_port=value["output_port"],
    )


def selection_input_to_public(value: SelectionInput) -> dict[str, str]:
    return {
        "node_id": value.node_id,
        "output_port": value.output_port,
    }


def context_selector_from_public(
    value: Mapping[str, Any],
) -> ContextSelector:
    if value["kind"] == "intrinsic":
        return IntrinsicObservationContext(value["kind"])
    if value["kind"] == "calibration":
        return CalibrationObservationContext(
            calibration_metric=value["calibration_metric"],
            calibration_value=value["calibration_value"],
            calibration_unit=value["calibration_unit"],
            population_id=value["population_id"],
            kind=value["kind"],
        )
    return PairwiseContextSelector(
        pairing_mode=value["pairing_mode"],
        normalization=value["normalization"],
        subject_role=value["subject_role"],
        reference_role=value["reference_role"],
        kind=value["kind"],
    )


def context_selector_to_public(value: ContextSelector) -> dict[str, Any]:
    if isinstance(value, IntrinsicObservationContext):
        return {"kind": value.kind}
    if isinstance(value, CalibrationObservationContext):
        return {
            "kind": value.kind,
            "calibration_metric": value.calibration_metric,
            "calibration_value": value.calibration_value,
            "calibration_unit": value.calibration_unit,
            "population_id": value.population_id,
        }
    return {
        "kind": value.kind,
        "subject_role": value.subject_role,
        "reference_role": value.reference_role,
        "pairing_mode": value.pairing_mode,
        "normalization": value.normalization,
    }


def _reference_from_public(
    value: Mapping[str, Any],
    name: str,
) -> ExactContractReference:
    raw = value[name]
    return ExactContractReference(
        contract_kind=raw["contract_kind"],
        contract_id=raw["contract_id"],
        contract_version=raw["contract_version"],
        contract_digest=raw["contract_digest"],
    )


def _reference_to_public(
    value: ExactContractReference,
) -> dict[str, str]:
    return {
        "contract_kind": value.contract_kind,
        "contract_id": value.contract_id,
        "contract_version": value.contract_version,
        "contract_digest": value.contract_digest,
    }


def observation_selector_from_public(
    value: Mapping[str, Any],
) -> ObservationSelector:
    return ObservationSelector(
        selector_id=value["selector_id"],
        candidate_input=selection_input_from_public(value["candidate_input"]),
        score_collection_input=selection_input_from_public(
            value["score_collection_input"]
        ),
        metric=_reference_from_public(value, "metric"),
        method=_reference_from_public(value, "method"),
        context_selector=context_selector_from_public(value["context_selector"]),
        source_partition=value["source_partition"],
        match_cardinality=value["match_cardinality"],
        missing_policy=value["missing_policy"],
    )


def observation_selector_to_public(
    value: ObservationSelector | ObservationSelectorProvenance,
) -> dict[str, Any]:
    return {
        "selector_id": value.selector_id,
        "candidate_input": selection_input_to_public(value.candidate_input),
        "score_collection_input": selection_input_to_public(
            value.score_collection_input
        ),
        "source_partition": value.source_partition,
        "metric": _reference_to_public(value.metric),
        "method": _reference_to_public(value.method),
        "context_selector": context_selector_to_public(
            value.context_selector
        ),
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def selection_objective_from_public(
    value: Mapping[str, Any],
) -> SelectionObjective:
    return SelectionObjective(
        objective_id=value["objective_id"],
        candidate_input=selection_input_from_public(value["candidate_input"]),
        score_collection_input=selection_input_from_public(
            value["score_collection_input"]
        ),
        metric=_reference_from_public(value, "metric"),
        method=_reference_from_public(value, "method"),
        context_selector=context_selector_from_public(value["context_selector"]),
        utility_transform=_reference_from_public(value, "utility_transform"),
        utility_parameters=value["utility_parameters"],
        weight=value["weight"],
        source_partition=value["source_partition"],
        match_cardinality=value["match_cardinality"],
        missing_policy=value["missing_policy"],
    )


def selection_objective_to_public(
    value: SelectionObjective,
) -> dict[str, Any]:
    return {
        "objective_id": value.objective_id,
        "candidate_input": selection_input_to_public(value.candidate_input),
        "score_collection_input": selection_input_to_public(
            value.score_collection_input
        ),
        "source_partition": value.source_partition,
        "metric": _reference_to_public(value.metric),
        "method": _reference_to_public(value.method),
        "context_selector": context_selector_to_public(
            value.context_selector
        ),
        "utility_transform": _reference_to_public(value.utility_transform),
        "utility_parameters": thaw_i_json(value.utility_parameters),
        "weight": value.weight,
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def objective_provenance_to_public(
    value: SelectionObjectiveProvenance,
) -> dict[str, Any]:
    return {
        "objective_id": value.objective_id,
        "candidate_input": selection_input_to_public(value.candidate_input),
        "score_collection_input": selection_input_to_public(
            value.score_collection_input
        ),
        "source_partition": value.source_partition,
        "metric": _reference_to_public(value.metric),
        "method": _reference_to_public(value.method),
        "context_selector": context_selector_to_public(
            value.context_selector
        ),
        "utility_transform": _reference_to_public(value.utility_transform),
        "utility_parameters": thaw_i_json(value.utility_parameters),
        "declared_weight": value.declared_weight,
        "effective_weight": value.effective_weight,
        "match_cardinality": value.match_cardinality,
        "missing_policy": value.missing_policy,
    }


def selection_provenance_to_public(
    value: SelectionProvenance,
) -> dict[str, Any]:
    return {
        "objectives": [
            objective_provenance_to_public(objective)
            for objective in value.objectives
        ]
    }
