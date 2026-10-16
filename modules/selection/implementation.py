"""Deterministic selection over exact Workflow-owned scientific objectives."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from core.operation import OperationCall
from core.scoring.selection import (
    ResolvedSelectionObjective,
    SelectionError,
    rank_candidates_by_weighted_utility,
    resolve_candidate_utilities_from_facts,
    weighted_utility_totals,
)
from datatypes.candidate import (
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.observation import (
    ScoreCollection,
)


class SelectionImplementation:
    """Execute one controlled filter, sort, or top-k operation."""

    def __init__(
        self,
        *,
        operation: str,
        objectives: tuple[ResolvedSelectionObjective, ...],
    ) -> None:
        self._operation = operation
        self._objectives = {
            item.objective_id: item
            for item in objectives
        }


    def execute(self, call: OperationCall) -> dict[str, CandidateCollection]:
        candidates = call.inputs["candidates"].value
        candidate_data_references = self._candidate_data_references(
            call,
        )
        if self._operation == "manual":
            requested = {
                (item["candidate_id"], item["data_type_id"], item["content_digest"])
                for item in call.node_parameters["selected_candidates"]
            }
            present = {
                (item.candidate_id, item.data_type_id, item.content_digest)
                for item in candidate_data_references.values()
            }
            missing = requested - present
            if missing:
                raise SelectionError(
                    f"Manual selection references missing from current input: {len(missing)}; "
                    f"first Candidate: {sorted(missing)[0][0]}",
                    diagnostic={
                        "missing_candidate_count": len(missing),
                        "first_missing_candidate_reference": dict(zip(
                            ("candidate_id", "data_type_id", "content_digest"),
                            sorted(missing)[0], strict=True,
                        )),
                    },
                )
            selected_ids = {item[0] for item in requested}
            return self._output(candidates, [
                item for item in candidates.items
                if item.candidate_id in selected_ids
            ])
        scores = call.inputs["scores"].value
        if self._operation in {"weighted_rank", "diversity"}:
            return self._execute_multi_objective(
                candidates=candidates,
                score_collections=scores,
                node_parameters=call.node_parameters,
                candidate_data_references=candidate_data_references,
            )
        out_of_scope_policy = call.node_parameters["out_of_scope_policy"]

        objective_id = call.node_parameters["objective_id"]
        objective_facts = self._objectives[objective_id]
        profile = resolve_candidate_utilities_from_facts(
            candidate_inputs={objective_facts.candidate_input: candidates},
            score_collection_inputs={
                objective_facts.score_collection_input: scores
            },
            objectives=(objective_facts,),
            out_of_scope_policy=out_of_scope_policy,
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
        return self._output(candidates, selected)

    def _output(
        self, candidates: CandidateCollection, selected: list[Any]
    ) -> dict[str, CandidateCollection]:
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
        score_collections: tuple[ScoreCollection, ...],
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
        profile = resolve_candidate_utilities_from_facts(
            candidate_inputs={candidate_reference: candidates},
            score_collection_inputs={
                objective.score_collection_input: scores
                for objective, scores in zip(
                    objectives,
                    score_collections,
                    strict=True,
                )
            },
            objectives=objectives,
            candidate_data_references=candidate_data_references,
        )
        aggregate = weighted_utility_totals(profile)
        if self._operation == "weighted_rank":
            selected = list(rank_candidates_by_weighted_utility(profile))
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

    @staticmethod
    def _candidate_data_references(
        call: OperationCall,
    ) -> Mapping[str, CandidateDataReference]:
        return {
            reference.candidate_id: reference
            for reference in call.inputs["candidates"].candidate_data
        }
