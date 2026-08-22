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
    context_selector_canonical,
    objective_provenance_canonical,
    observation_selector_canonical,
    selection_input_canonical,
    selection_objective_canonical,
    selection_provenance_canonical,
)
from datatypes.exact_reference import ExactContractReference
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
    return selection_input_canonical(value)


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
    return context_selector_canonical(value)


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
    return observation_selector_canonical(value)


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
    return selection_objective_canonical(value)


def objective_provenance_to_public(
    value: SelectionObjectiveProvenance,
) -> dict[str, Any]:
    return objective_provenance_canonical(value)


def selection_provenance_to_public(
    value: SelectionProvenance,
) -> dict[str, Any]:
    return selection_provenance_canonical(value)
