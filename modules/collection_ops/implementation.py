"""Direct collection operations over exact v2 domain values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.operation import AdmittedPort, OperationCall
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.observation import (
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ScoreCollection,
)


_CONCAT_CANDIDATE_PORTS = (
    "candidates_a",
    "candidates_b",
    "candidates_c",
)
_INTERSECTION_PORTS = (
    *_CONCAT_CANDIDATE_PORTS,
    "candidates_d",
)
_SCORE_PORTS = ("scores_a", "scores_b", "scores_c")
_PAIRING_PORTS = ("pairing_a", "pairing_b", "pairing_c")


class CollectionOpsImplementation:
    """Execute one deterministic, identity-preserving collection operation."""

    def __init__(self, operation: str) -> None:
        self._operation = operation

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if self._operation == "concat_candidates":
            return {"candidates": self._concat_candidates(call.inputs)}
        if self._operation == "merge_scores":
            return {"scores": self._merge_scores(call.inputs)}
        if self._operation == "concat_pairings":
            return {"pairing": self._concat_pairings(call.inputs)}
        if self._operation == "rebind_candidate_pairing":
            return {"pairing": self._rebind_candidate_pairing(call)}
        if self._operation == "pair_siblings_by_parent":
            return {"pairing": self._pair_siblings_by_parent(call)}
        if self._operation == "take_candidates":
            return {
                "candidates": self._take_candidates(
                    call.inputs,
                    call.node_parameters,
                )
            }
        if self._operation == "select_children_by_parent":
            return {
                "candidates": self._select_children_by_parent(call.inputs)
            }
        return {"candidates": self._intersect_candidates(call.inputs)}

    @staticmethod
    def _select_children_by_parent(
        inputs: Mapping[str, AdmittedPort],
    ) -> CandidateCollection:
        candidates = inputs["candidates"].value
        parents = inputs["parents"].value
        parent_ids = {candidate.candidate_id for candidate in parents.items}
        selected = []
        for candidate in candidates.items:
            if len(candidate.parent_ids) != 1:
                raise ValueError(
                    "each child Candidate must have exactly one parent"
                )
            if candidate.parent_ids[0] in parent_ids:
                selected.append(candidate)
        return CandidateCollection(
            collection_id="collection-ops-children-of-selected-parents",
            item_type=candidates.item_type,
            items=tuple(selected),
        )

    @staticmethod
    def _intersect_candidates(
        inputs: Mapping[str, AdmittedPort],
    ) -> CandidateCollection:
        supplied = [
            inputs[port].value
            for port in _INTERSECTION_PORTS
            if port in inputs
        ]
        if len(supplied) < 2:
            raise ValueError(
                "Candidate intersection requires at least two connected inputs"
            )
        first = supplied[0]
        if any(value.item_type != first.item_type for value in supplied[1:]):
            raise ValueError("Candidate intersection requires one exact item type")
        identities = [
            {candidate.candidate_id: candidate for candidate in value.items}
            for value in supplied
        ]
        selected = [
            candidate
            for candidate in first.items
            if all(
                index.get(candidate.candidate_id) == candidate
                for index in identities[1:]
            )
        ]
        return CandidateCollection(
            collection_id="collection-ops-intersected-candidates",
            item_type=first.item_type,
            items=tuple(selected),
        )

    @staticmethod
    def _take_candidates(
        inputs: Mapping[str, AdmittedPort],
        node_parameters: Mapping[str, Any],
    ) -> CandidateCollection:
        candidates = inputs["candidates"].value
        k = node_parameters["k"]
        if k > len(candidates.items):
            raise ValueError(
                "k cannot exceed Candidate input cardinality"
            )
        return CandidateCollection(
            collection_id=f"{candidates.collection_id}-first-{k}",
            item_type=candidates.item_type,
            items=list(candidates.items[:k]),
        )

    def _candidate_references(
        self,
        call: OperationCall,
        value: CandidateCollection,
        *,
        port: str,
    ) -> tuple[
        CandidateCollection,
        dict[str, tuple[Candidate, CandidateDataReference]],
    ]:
        if not value.items:
            raise ValueError(f"{port} must be a non-empty Candidate Collection")
        admitted = call.inputs[port]
        admitted_by_id = {
            entry.candidate_id: entry
            for entry in admitted.candidate_data
        }
        by_id = {
            candidate.candidate_id: (
                candidate,
                admitted_by_id[candidate.candidate_id],
            )
            for candidate in value.items
        }
        return value, by_id

    def _rebind_candidate_pairing(
        self,
        call: OperationCall,
    ) -> PairwiseCandidateMapping:
        inputs = call.inputs
        subjects, subjects_by_id = self._candidate_references(
            call,
            inputs["subjects"].value,
            port="subjects",
        )
        parents, parents_by_id = self._candidate_references(
            call,
            inputs["parents"].value,
            port="parents",
        )
        references, references_by_id = self._candidate_references(
            call,
            inputs["references"].value,
            port="references",
        )
        pairing = inputs["parent_pairing"].value
        parent_to_reference: dict[
            str, CandidateDataReference
        ] = {}
        seen_references: set[CandidateDataReference] = set()
        for entry in pairing.entries:
            parent = parents_by_id.get(entry.subject.candidate_id)
            reference = references_by_id.get(entry.reference.candidate_id)
            if (
                parent is None
                or reference is None
                or parent[1] != entry.subject
                or reference[1] != entry.reference
                or entry.subject.candidate_id in parent_to_reference
                or entry.reference in seen_references
            ):
                raise ValueError(
                    "parent_pairing contradicts exact Candidate identities "
                    "or content"
                )
            parent_to_reference[entry.subject.candidate_id] = entry.reference
            seen_references.add(entry.reference)
        if set(parent_to_reference) != set(parents_by_id):
            raise ValueError("parent_pairing is not complete for all parents")
        if seen_references != {
            reference for _, reference in references_by_id.values()
        }:
            raise ValueError(
                "parent_pairing is not complete for all references"
            )
        rebound: list[PairwiseCandidateMatch] = []
        used_parents: set[str] = set()
        used_references: set[str] = set()
        for subject in subjects.items:
            matching_parents = [
                parent_id
                for parent_id in subject.parent_ids
                if parent_id in parents_by_id
            ]
            if len(matching_parents) != 1:
                raise ValueError(
                    "each subject must name exactly one supplied parent"
                )
            parent_id = matching_parents[0]
            if subject.parent_ids != (parent_id,):
                raise ValueError(
                    "each subject must have exactly one total parent"
                )
            reference = parent_to_reference[parent_id]
            if (
                parent_id in used_parents
                or reference.candidate_id in used_references
            ):
                raise ValueError(
                    "pairing rebinding requires one subject per exact parent"
                )
            used_parents.add(parent_id)
            used_references.add(reference.candidate_id)
            rebound.append(PairwiseCandidateMatch(
                subject=subjects_by_id[subject.candidate_id][1],
                reference=reference,
            ))
        if used_parents != set(parents_by_id):
            raise ValueError("subjects do not cover every exact parent")
        return PairwiseCandidateMapping(rebound)

    def _pair_siblings_by_parent(
        self,
        call: OperationCall,
    ) -> PairwiseCandidateMapping:
        inputs = call.inputs
        subjects, subjects_by_id = self._candidate_references(
            call,
            inputs["subjects"].value,
            port="subjects",
        )
        references, references_by_id = self._candidate_references(
            call,
            inputs["references"].value,
            port="references",
        )

        def by_parent(
            collection: CandidateCollection,
            *,
            port: str,
        ) -> dict[str, Candidate]:
            indexed: dict[str, Candidate] = {}
            for candidate in collection.items:
                if len(candidate.parent_ids) != 1:
                    raise ValueError(
                        f"each {port} Candidate must have exactly one parent"
                    )
                parent_id = candidate.parent_ids[0]
                if not parent_id or parent_id in indexed:
                    raise ValueError(
                        f"{port} must contain exactly one Candidate per parent"
                    )
                indexed[parent_id] = candidate
            return indexed

        subjects_by_parent = by_parent(subjects, port="subjects")
        references_by_parent = by_parent(references, port="references")
        if set(subjects_by_parent) != set(references_by_parent):
            raise ValueError(
                "subject and reference Candidates must cover the same parents"
            )
        return PairwiseCandidateMapping([
            PairwiseCandidateMatch(
                subject=subjects_by_id[subject.candidate_id][1],
                reference=references_by_id[
                    references_by_parent[
                        subject.parent_ids[0]
                    ].candidate_id
                ][1],
            )
            for subject in subjects.items
        ])

    @staticmethod
    def _concat_candidates(
        inputs: Mapping[str, AdmittedPort],
    ) -> CandidateCollection:
        supplied = [
            (port, inputs[port].value)
            for port in _CONCAT_CANDIDATE_PORTS
            if port in inputs
        ]
        item_type = supplied[0][1].item_type
        candidates: list[Candidate] = []
        source_by_identity: dict[str, str] = {}
        for port, collection in supplied:
            if collection.item_type != item_type:
                raise ValueError(
                    "Candidate concatenation requires one exact item type"
                )
            for candidate in collection.items:
                previous = source_by_identity.get(candidate.candidate_id)
                if previous is not None:
                    raise ValueError(
                        "Candidate identity occurs in more than one input "
                        f"partition: {previous}, {port}"
                    )
                source_by_identity[candidate.candidate_id] = port
                candidates.append(candidate)
        return CandidateCollection(
            collection_id="collection-ops-concatenated-candidates",
            item_type=item_type,
            items=candidates,
        )

    @staticmethod
    def _merge_scores(inputs: Mapping[str, AdmittedPort]) -> ScoreCollection:
        return ScoreCollection(
            collection_id="collection-ops-merged-scores",
            entries=[
                entry
                for port in _SCORE_PORTS
                if port in inputs
                for entry in inputs[port].value.entries
            ],
        )

    @staticmethod
    def _concat_pairings(
        inputs: Mapping[str, AdmittedPort],
    ) -> PairwiseCandidateMapping:
        supplied = [
            (port, inputs[port].value)
            for port in _PAIRING_PORTS
            if port in inputs
        ]
        entries: list[PairwiseCandidateMatch] = []
        subject_sources: dict[CandidateDataReference, str] = {}
        reference_sources: dict[CandidateDataReference, str] = {}
        for port, pairing in supplied:
            for entry in pairing.entries:
                if entry.subject in subject_sources:
                    raise ValueError(
                        "Candidate pairing subject occurs in more than one "
                        f"input partition: {subject_sources[entry.subject]}, {port}"
                    )
                if entry.reference in reference_sources:
                    raise ValueError(
                        "Candidate pairing reference occurs in more than one "
                        f"input partition: {reference_sources[entry.reference]}, {port}"
                    )
                subject_sources[entry.subject] = port
                reference_sources[entry.reference] = port
                entries.append(entry)
        return PairwiseCandidateMapping(tuple(entries))
