"""Deterministic selection over exact Workflow-owned scientific objectives."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from core.port_types import canonical_sha256
from core.scoring_v2 import (
    SelectionError,
    SelectionObjective,
    resolve_objective_observations,
    resolve_candidate_utilities,
    resolve_selection_objective,
    select_candidates,
)
from datatypes import (
    CandidateCollection,
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
        if self._operation in {"weighted_rank", "pareto", "diversity"}:
            return self._execute_multi_objective(
                candidates=candidates,
                scores=scores,
                node_parameters=node_parameters,
            )
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

        matching = resolve_objective_observations(
            candidates=candidates,
            collection=scores,
            objective=objective,
            out_of_scope_policy=out_of_scope_policy,
            duplicate_policy="error",
        )
        scoped_scores = ScoreCollection(
            collection_id=f"{scores.collection_id}.selected-scope",
            entries=list(matching.values()),
        )
        ranked = select_candidates(
            candidate_inputs={objective.candidate_input: candidates},
            score_collection_inputs={
                objective.score_collection_input: scoped_scores
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

    def _execute_multi_objective(
        self,
        *,
        candidates: CandidateCollection,
        scores: ScoreCollection,
        node_parameters: Mapping[str, Any],
    ) -> dict[str, CandidateCollection]:
        objective_ids = node_parameters.get("objective_ids")
        if (
            not isinstance(objective_ids, (list, tuple))
            or not objective_ids
            or not all(isinstance(item, str) for item in objective_ids)
            or len(objective_ids) != len(set(objective_ids))
        ):
            raise ValueError(
                "multi-objective selection requires unique objective_ids"
            )
        objectives = tuple(
            self._objectives.get(objective_id)
            for objective_id in objective_ids
        )
        if any(objective is None for objective in objectives):
            raise ValueError(
                "selection objective_ids do not resolve compiled objectives"
            )
        if node_parameters.get("tie_policy") != "candidate_id_ascending":
            raise ValueError("selection tie policy is unsupported")
        typed_objectives = tuple(
            objective
            for objective in objectives
            if objective is not None
        )
        candidate_references = {
            objective.candidate_input for objective in typed_objectives
        }
        score_references = {
            objective.score_collection_input
            for objective in typed_objectives
        }
        if len(candidate_references) != 1 or len(score_references) != 1:
            raise SelectionError(
                "multi-objective selection requires exact shared Candidate "
                "and Score Collection inputs"
            )
        profile = resolve_candidate_utilities(
            candidate_inputs={next(iter(candidate_references)): candidates},
            score_collection_inputs={next(iter(score_references)): scores},
            objectives=typed_objectives,
            catalog=self._catalog,
        )
        aggregate = {
            candidate_id: math.fsum(
                utility * weight
                for utility, weight in zip(
                    utilities,
                    profile.effective_weights,
                    strict=True,
                )
            )
            for candidate_id, utilities in profile.utilities.items()
        }
        if self._operation == "weighted_rank":
            selected = sorted(
                candidates.items,
                key=lambda candidate: (
                    -aggregate[candidate.candidate_id],
                    candidate.candidate_id,
                ),
            )
        elif self._operation == "pareto":
            dominated: set[str] = set()
            candidate_ids = tuple(sorted(profile.utilities))
            for candidate_id in candidate_ids:
                vector = profile.utilities[candidate_id]
                for other_id in candidate_ids:
                    if other_id == candidate_id:
                        continue
                    other = profile.utilities[other_id]
                    if (
                        all(
                            other_value >= value
                            for other_value, value in zip(
                                other,
                                vector,
                                strict=True,
                            )
                        )
                        and any(
                            other_value > value
                            for other_value, value in zip(
                                other,
                                vector,
                                strict=True,
                            )
                        )
                    ):
                        dominated.add(candidate_id)
                        break
            candidates_by_id = {
                candidate.candidate_id: candidate
                for candidate in candidates.items
            }
            selected = [
                candidates_by_id[candidate_id]
                for candidate_id in candidate_ids
                if candidate_id not in dominated
            ]
        elif self._operation == "diversity":
            k = node_parameters.get("k")
            if type(k) is not int or k < 1:
                raise ValueError(
                    "diversity selection requires a positive integer k"
                )
            if k > len(candidates.items):
                raise ValueError(
                    "diversity selection k cannot exceed Candidate input "
                    "cardinality"
                )
            candidates_by_id = {
                candidate.candidate_id: candidate
                for candidate in candidates.items
            }
            first_id = min(
                profile.utilities,
                key=lambda candidate_id: (
                    -aggregate[candidate_id],
                    candidate_id,
                ),
            )
            selected_ids = [first_id]
            remaining = set(profile.utilities) - {first_id}

            def distance(left_id: str, right_id: str) -> float:
                return math.sqrt(
                    math.fsum(
                        weight * ((left - right) ** 2)
                        for left, right, weight in zip(
                            profile.utilities[left_id],
                            profile.utilities[right_id],
                            profile.effective_weights,
                            strict=True,
                        )
                    )
                )

            while len(selected_ids) < k:
                next_id = min(
                    remaining,
                    key=lambda candidate_id: (
                        -min(
                            distance(candidate_id, selected_id)
                            for selected_id in selected_ids
                        ),
                        candidate_id,
                    ),
                )
                selected_ids.append(next_id)
                remaining.remove(next_id)
            selected = [
                candidates_by_id[candidate_id]
                for candidate_id in selected_ids
            ]
        else:
            raise RuntimeError("unknown multi-objective selection operation")

        collection_identity = canonical_sha256(
            {
                "schema_namespace": (
                    "protein-workbench-multi-objective-selection-output/v2"
                ),
                "operation": self._operation,
                "input_collection_id": candidates.collection_id,
                "objectives": profile.public_provenance()["objectives"],
                "parameters": {
                    name: list(value) if isinstance(value, tuple) else value
                    for name, value in node_parameters.items()
                },
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
                items=list(selected),
            )
        }

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
