"""Deterministic selection over exact Workflow-owned scientific objectives."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from core.operation import OperationCall
from core.port_types import canonical_sha256
from core.scoring_v2 import (
    ResolvedObservationSelector,
    ResolvedSelectionObjective,
    SelectionError,
    observation_selector_identity_facts_from_facts,
    rank_candidates_by_weighted_utility,
    resolve_candidate_utilities_from_facts,
    resolve_objective_observations,
    selection_objective_identity_facts_from_facts,
    weighted_utility_totals,
)
from datatypes import (
    CandidateCollection,
    CandidateDataReference,
    PairwiseObservationContext,
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
            item.objective.objective_id: item
            for item in objectives
        }
        self._selectors = {
            item.selector.selector_id: item
            for item in selectors
        }

    def execute(self, call: OperationCall) -> dict[str, CandidateCollection]:
        if call.binding_parameters:
            raise ValueError("selection accepts no Binding parameters")
        candidates = call.inputs.get("candidates")
        scores = call.inputs.get("scores")
        if type(candidates) is not CandidateCollection:
            raise ValueError("selection requires one exact Candidate Collection")
        if type(scores) is not ScoreCollection:
            raise ValueError("selection requires one exact Score Collection")
        candidate_data_references = self._candidate_data_references(
            call,
            candidates,
        )
        if self._operation in {"weighted_rank", "pareto", "diversity"}:
            return self._execute_multi_objective(
                candidates=candidates,
                scores=scores,
                node_parameters=call.node_parameters,
                candidate_data_references=candidate_data_references,
            )
        if (
            call.node_parameters.get("tie_policy")
            != "candidate_id_ascending"
        ):
            raise ValueError("selection tie policy is unsupported")
        out_of_scope_policy = call.node_parameters.get("out_of_scope_policy")
        if out_of_scope_policy not in {"error", "ignore"}:
            raise ValueError("selection out-of-scope policy is unsupported")

        if self._operation == "filter":
            selector_facts = self._selectors.get(
                call.node_parameters.get("selector_id")
            )
            if selector_facts is None:
                raise ValueError(
                    "selection selector_id does not resolve one compiled "
                    "Observation Selector"
                )
            selector = selector_facts.selector
            matching = resolve_objective_observations(
                candidates=candidates,
                collection=scores,
                objective=selector,
                out_of_scope_policy=out_of_scope_policy,
                duplicate_policy="error",
            )
            self._require_exact_observation_subjects(
                matching,
                candidate_data_references,
            )
            selected = self._filter(
                candidates=candidates,
                matching=matching,
                operator=call.node_parameters.get("operator"),
                threshold=call.node_parameters.get("threshold"),
            )
            selection_contract = (
                observation_selector_identity_facts_from_facts(
                    (selector_facts,),
                    candidate_input_port="candidates",
                    score_collection_input_port="scores",
                )[0]
            )
        else:
            objective_id = call.node_parameters.get("objective_id")
            objective_facts = self._objectives.get(objective_id)
            if objective_facts is None:
                raise ValueError(
                    "selection objective_id does not resolve one compiled "
                    "objective"
                )
            objective = objective_facts.objective
            if objective.match_cardinality != "exactly_one":
                raise ValueError(
                    "selection requires exactly_one match cardinality"
                )
            if objective.missing_policy != "error":
                raise ValueError(
                    "selection requires fail-closed missing policy"
                )
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
            profile = resolve_candidate_utilities_from_facts(
                candidate_inputs={objective.candidate_input: candidates},
                score_collection_inputs={
                    objective.score_collection_input: scoped_scores
                },
                objectives=(objective_facts,),
                candidate_data_references=candidate_data_references,
            )
            ranked = rank_candidates_by_weighted_utility(profile)
            selection_contract = (
                selection_objective_identity_facts_from_facts(
                    (objective_facts,),
                    candidate_input_port="candidates",
                    score_collection_input_port="scores",
                )[0]
            )

        if self._operation == "sort":
            selected = list(ranked)
        elif self._operation == "top_k":
            k = call.node_parameters.get("k")
            if type(k) is not int or k < 1:
                raise ValueError("top-k requires a positive integer k")
            if k > len(candidates.items):
                raise ValueError(
                    "top-k k cannot exceed Candidate input cardinality"
                )
            selected = list(ranked[:k])
        elif self._operation == "filter":
            pass
        else:
            raise RuntimeError("unknown selection operation")

        collection_identity = canonical_sha256(
            {
                "schema_namespace": "protein-workbench-selection-output/v4",
                "operation": self._operation,
                "input_collection_id": candidates.collection_id,
                "selection_contract": selection_contract,
                "parameters": {
                    name: value
                    for name, value in call.node_parameters.items()
                    if name not in {"objective_id", "selector_id"}
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
            item for item in objectives if item is not None
        )
        candidate_references = {
            item.objective.candidate_input for item in typed_objectives
        }
        score_references = {
            item.objective.score_collection_input for item in typed_objectives
        }
        if len(candidate_references) != 1 or len(score_references) != 1:
            raise SelectionError(
                "multi-objective selection requires exact shared Candidate "
                "and Score Collection inputs"
            )
        profile = resolve_candidate_utilities_from_facts(
            candidate_inputs={next(iter(candidate_references)): candidates},
            score_collection_inputs={next(iter(score_references)): scores},
            objectives=typed_objectives,
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
                    "protein-workbench-multi-objective-selection-output/v4"
                ),
                "operation": self._operation,
                "input_collection_id": candidates.collection_id,
                "objectives": list(
                    selection_objective_identity_facts_from_facts(
                        typed_objectives,
                        candidate_input_port="candidates",
                        score_collection_input_port="scores",
                    )
                ),
                "parameters": {
                    name: list(value) if isinstance(value, tuple) else value
                    for name, value in node_parameters.items()
                    if name != "objective_ids"
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
    ) -> list[Any]:
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

    @staticmethod
    def _candidate_data_references(
        call: OperationCall,
        candidates: CandidateCollection,
    ) -> Mapping[str, CandidateDataReference]:
        admitted = call.input_content_digests.get("candidates")
        if admitted is None:
            raise ValueError(
                "selection Candidate content identities were not admitted"
            )
        if len(admitted.candidate_data) != len(candidates.items):
            raise ValueError(
                "selection Candidate content identities are incomplete"
            )
        resolved: dict[str, CandidateDataReference] = {}
        for candidate, reference in zip(
            candidates.items,
            admitted.candidate_data,
            strict=True,
        ):
            if candidate.candidate_id != reference.candidate_id:
                raise ValueError(
                    "selection Candidate content identity names a different "
                    "Candidate"
                )
            resolved[reference.candidate_id] = reference
        if len(resolved) != len(admitted.candidate_data):
            raise ValueError(
                "selection has duplicate admitted Candidate identities"
            )
        return resolved

    @staticmethod
    def _require_exact_observation_subjects(
        observations: Mapping[str, ScoreObservation],
        candidates: Mapping[str, CandidateDataReference],
    ) -> None:
        for candidate_id, observation in observations.items():
            expected = candidates.get(candidate_id)
            if expected is None or observation.subject != expected:
                raise SelectionError(
                    "Observation subject does not match the exact Candidate "
                    "Data Reference"
                )
            if (
                isinstance(observation.context, PairwiseObservationContext)
                and observation.context.subject.candidate != expected
            ):
                raise SelectionError(
                    "Pairwise Context subject does not match the exact "
                    "Candidate Data Reference"
                )
