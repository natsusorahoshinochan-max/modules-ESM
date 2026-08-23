"""Deterministic selection over exact Workflow-owned scientific objectives."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from core.operation import OperationCall
from core.scoring.selection import (
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
    rank_candidates_by_weighted_utility,
    resolve_candidate_utilities_from_facts,
    resolve_objective_observations,
    weighted_utility_totals,
)
from datatypes.candidate import (
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.observation import (
    ScoreCollection,
    ScoreObservation,
)


class SelectionImplementation:
    """Execute one controlled filter, sort, or top-k operation."""

    def __init__(
        self,
        *,
        operation: str,
        objectives: tuple[ResolvedSelectionObjective, ...],
        selectors: tuple[ResolvedObservationSelector, ...],
    ) -> None:
        self._operation = operation
        self._objectives = {
            item.objective_id: item
            for item in objectives
        }
        self._selectors = {
            item.selector_id: item
            for item in selectors
        }

    def execute(self, call: OperationCall) -> dict[str, CandidateCollection]:
        candidates = call.inputs["candidates"].value
        scores = call.inputs["scores"].value
        candidate_data_references = self._candidate_data_references(
            call,
        )
        if self._operation in {"weighted_rank", "pareto", "diversity"}:
            return self._execute_multi_objective(
                candidates=candidates,
                scores=scores,
                node_parameters=call.node_parameters,
                candidate_data_references=candidate_data_references,
            )
        out_of_scope_policy = call.node_parameters["out_of_scope_policy"]

        if self._operation == "filter":
            selector_facts = self._selectors[
                call.node_parameters["selector_id"]
            ]
            matching = resolve_objective_observations(
                candidates=candidates,
                collection=scores,
                objective=selector_facts,
                out_of_scope_policy=out_of_scope_policy,
            )
            selected = self._filter(
                candidates=candidates,
                matching=matching,
                operator=call.node_parameters["operator"],
                threshold=call.node_parameters["threshold"],
            )
        else:
            objective_id = call.node_parameters["objective_id"]
            objective_facts = self._objectives[objective_id]
            matching = resolve_objective_observations(
                candidates=candidates,
                collection=scores,
                objective=objective_facts,
                out_of_scope_policy=out_of_scope_policy,
            )
            scoped_scores = ScoreCollection(
                collection_id=f"{scores.collection_id}.selected-scope",
                entries=list(matching.values()),
            )
            profile = resolve_candidate_utilities_from_facts(
                candidate_inputs={objective_facts.candidate_input: candidates},
                score_collection_inputs={
                    objective_facts.score_collection_input: scoped_scores
                },
                objectives=(objective_facts,),
                candidate_data_references=candidate_data_references,
            )
            ranked = rank_candidates_by_weighted_utility(profile)

        if self._operation == "sort":
            selected = list(ranked)
        elif self._operation == "top_k":
            k = call.node_parameters["k"]
            if k > len(candidates.items):
                raise ValueError(
                    "top-k k cannot exceed Candidate input cardinality"
                )
            selected = list(ranked[:k])
        return {
            "candidates": CandidateCollection(
                collection_id=f"selection-{self._operation}",
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
        candidate_data_references: Mapping[
            str,
            CandidateDataReference,
        ],
    ) -> dict[str, CandidateCollection]:
        objective_ids = node_parameters["objective_ids"]
        objectives = tuple(
            self._objectives[objective_id]
            for objective_id in objective_ids
        )
        candidate_reference = objectives[0].candidate_input
        score_reference = objectives[0].score_collection_input
        profile = resolve_candidate_utilities_from_facts(
            candidate_inputs={candidate_reference: candidates},
            score_collection_inputs={score_reference: scores},
            objectives=objectives,
            candidate_data_references=candidate_data_references,
        )
        aggregate = weighted_utility_totals(profile)
        if self._operation == "weighted_rank":
            selected = list(rank_candidates_by_weighted_utility(profile))
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
        else:
            k = node_parameters["k"]
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
        return {
            "candidates": CandidateCollection(
                collection_id=f"selection-{self._operation}",
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
    ) -> list[Any]:
        comparisons = {
            ">": lambda value: value > threshold,
            ">=": lambda value: value >= threshold,
            "<": lambda value: value < threshold,
            "<=": lambda value: value <= threshold,
            "==": lambda value: value == threshold,
            "!=": lambda value: value != threshold,
        }
        comparison = comparisons[operator]
        return [
            candidate
            for candidate in candidates.items
            if comparison(matching[candidate.candidate_id].value)
        ]

    @staticmethod
    def _candidate_data_references(
        call: OperationCall,
    ) -> Mapping[str, CandidateDataReference]:
        return {
            reference.candidate_id: reference
            for reference in call.inputs["candidates"].candidate_data
        }
