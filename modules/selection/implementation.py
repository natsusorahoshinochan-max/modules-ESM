"""Deterministic selection over exact Workflow-owned scientific objectives."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.port_types import CatalogBuildError, canonical_json_bytes, canonical_sha256
from core.scoring_v2 import (
    PairwiseContextSelector,
    SelectionError,
    SelectionInput,
    SelectionObjective,
    resolve_selection_objective,
    select_candidates,
)
from datatypes import (
    CandidateCollection,
    IntrinsicObservationContext,
    PairwiseObservationContext,
    Score,
    ScoreCollection,
    ScoreObservation,
)


class SelectionImplementation:
    """Execute one controlled filter, sort, or top-k operation."""

    def __init__(
        self,
        *,
        operation: str,
        execution_plan: Any,
        catalog: Any,
    ) -> None:
        self._operation = operation
        self._catalog = catalog
        self._objectives = {
            objective.objective_id: objective
            for objective in execution_plan.selection_objectives
        }

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, CandidateCollection]:
        if binding_parameters:
            raise ValueError("selection accepts no Binding parameters")
        candidates = inputs.get("candidates")
        scores = inputs.get("scores")
        if type(candidates) is not CandidateCollection:
            raise ValueError("selection requires one exact Candidate Collection")
        if type(scores) is not ScoreCollection:
            raise ValueError("selection requires one exact Score Collection")
        objective_id = node_parameters.get("objective_id")
        objective = self._objectives.get(objective_id)
        if objective is None:
            raise ValueError(
                "selection objective_id does not resolve one compiled objective"
            )
        if objective.match_cardinality != "exactly_one":
            raise ValueError("selection requires exactly_one match cardinality")
        if objective.missing_policy != "error":
            raise ValueError("selection requires fail-closed missing policy")
        if (
            node_parameters.get("tie_policy")
            != "candidate_id_ascending"
        ):
            raise ValueError("selection tie policy is unsupported")
        out_of_scope_policy = node_parameters.get("out_of_scope_policy")
        if out_of_scope_policy not in {"error", "ignore"}:
            raise ValueError("selection out-of-scope policy is unsupported")

        matching = self._matching_observations(
            candidates=candidates,
            scores=scores,
            objective=objective,
            out_of_scope_policy=out_of_scope_policy,
        )
        ranked = select_candidates(
            candidate_inputs={objective.candidate_input: candidates},
            score_collection_inputs={
                objective.score_collection_input: scores
            },
            objectives=(objective,),
            catalog=self._catalog,
            limit=max(1, len(candidates.items)),
        ).candidates.items

        if self._operation == "filter":
            selected = self._filter(
                candidates=candidates,
                matching=matching,
                operator=node_parameters.get("operator"),
                threshold=node_parameters.get("threshold"),
                objective=objective,
            )
        elif self._operation == "sort":
            selected = list(ranked)
        elif self._operation == "top_k":
            k = node_parameters.get("k")
            if type(k) is not int or k < 1:
                raise ValueError("top-k requires a positive integer k")
            if k > len(candidates.items):
                raise ValueError(
                    "top-k k cannot exceed Candidate input cardinality"
                )
            selected = list(ranked[:k])
        else:
            raise RuntimeError("unknown selection operation")

        collection_identity = canonical_sha256(
            {
                "schema_namespace": "protein-workbench-selection-output/v2",
                "operation": self._operation,
                "input_collection_id": candidates.collection_id,
                "objective": objective.to_public(),
                "parameters": dict(node_parameters),
                "selected_candidate_ids": [
                    candidate.candidate_id for candidate in selected
                ],
            }
        ).removeprefix("sha256:")
        return {
            "candidates": CandidateCollection(
                collection_id=(
                    f"selection-{self._operation}-{collection_identity}"
                ),
                item_type=candidates.item_type,
                items=selected,
            )
        }

    def _matching_observations(
        self,
        *,
        candidates: CandidateCollection,
        scores: ScoreCollection,
        objective: SelectionObjective,
        out_of_scope_policy: str,
    ) -> dict[str, ScoreObservation]:
        candidate_ids = [candidate.candidate_id for candidate in candidates.items]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("selection Candidate input has duplicate identities")
        candidate_set = set(candidate_ids)
        seen: dict[tuple[object, ...], bytes] = {}
        matches: dict[str, ScoreObservation] = {}
        for entry in scores.entries:
            if isinstance(entry, Score):
                raise ValueError("selection rejects legacy subject-free scores")
            if type(entry) is not ScoreObservation:
                raise ValueError("selection requires exact typed Observations")
            try:
                encoded = canonical_json_bytes(entry.value)
            except CatalogBuildError as error:
                raise ValueError(
                    "selection Observation value must be canonical I-JSON"
                ) from error
            previous = seen.get(entry.identity)
            if previous is not None:
                if previous != encoded:
                    raise ValueError(
                        "selection has a conflicting observation identity"
                    )
                raise ValueError(
                    "selection has a duplicate observation identity"
                )
            seen[entry.identity] = encoded
            in_scope = (
                entry.candidate_id in candidate_set
                and entry.source_partition == objective.source_partition
                and entry.metric == objective.metric
                and entry.method == objective.method
                and _context_matches(entry.context, objective.context_selector)
            )
            if not in_scope:
                if out_of_scope_policy == "error":
                    raise ValueError(
                        "selection received an out-of-scope observation"
                    )
                continue
            if entry.candidate_id in matches:
                raise ValueError(
                    "selection requires exactly one observation per Candidate"
                )
            matches[entry.candidate_id] = entry
        missing = [
            candidate_id
            for candidate_id in candidate_ids
            if candidate_id not in matches
        ]
        if missing:
            raise ValueError(
                "selection has a missing observation for Candidate "
                f"{missing[0]!r}"
            )
        return matches

    def _filter(
        self,
        *,
        candidates: CandidateCollection,
        matching: Mapping[str, ScoreObservation],
        operator: object,
        threshold: object,
        objective: SelectionObjective,
    ) -> list[Any]:
        metric, _, _, _ = resolve_selection_objective(
            objective,
            self._catalog,
        )
        if metric.descriptor.get("value_shape") != "scalar":
            raise SelectionError(
                "filter requires a scalar exact Metric Definition"
            )
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
        ):
            raise ValueError("filter threshold must be numeric")
        comparisons = {
            ">": lambda value: value > threshold,
            ">=": lambda value: value >= threshold,
            "<": lambda value: value < threshold,
            "<=": lambda value: value <= threshold,
            "==": lambda value: value == threshold,
            "!=": lambda value: value != threshold,
        }
        comparison = comparisons.get(operator)
        if comparison is None:
            raise ValueError("filter operator is unsupported")
        return [
            candidate
            for candidate in candidates.items
            if comparison(matching[candidate.candidate_id].value)
        ]


def _context_matches(context: object, selector: object) -> bool:
    if isinstance(selector, IntrinsicObservationContext):
        return context == selector
    return (
        isinstance(selector, PairwiseContextSelector)
        and isinstance(context, PairwiseObservationContext)
        and context.kind == selector.kind
        and context.subject.role == selector.subject_role
        and context.reference.role == selector.reference_role
        and context.pairing_mode == selector.pairing_mode
        and context.normalization == selector.normalization
    )
