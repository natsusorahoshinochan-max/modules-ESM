"""Direct collection operations over exact v2 domain values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.operation import AdmittedPort, OperationCall
from datatypes.candidate import Candidate, CandidateCollection, CandidateDataReference
from datatypes.observation import (
    CandidateRelation,
    CandidateRelationEntry,
    ScoreCollection,
)


_CONCAT_CANDIDATE_PORTS = ("candidates_a", "candidates_b", "candidates_c")
_INTERSECTION_PORTS = (*_CONCAT_CANDIDATE_PORTS, "candidates_d")
_SCORE_PORTS = ("scores_a", "scores_b", "scores_c")
_RELATION_PORTS = ("relation_a", "relation_b", "relation_c")


class CollectionOpsImplementation:
    """Execute one deterministic collection or Candidate-relation operation."""

    def __init__(self, operation: str) -> None:
        self._operation = operation

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if self._operation == "concat_candidates":
            return {"candidates": self._concat_candidates(call.inputs)}
        if self._operation == "merge_scores":
            return {"scores": self._merge_scores(call.inputs)}
        if self._operation == "concat_relations":
            return {"relation": self._concat_relations(call.inputs)}
        if self._operation == "relate_by_parent":
            return {"relation": self._relate_by_parent(call)}
        if self._operation == "relate_to_single_reference":
            return {"relation": self._relate_to_single_reference(call)}
        if self._operation == "compose_relations":
            return {"relation": self._compose_relations(call.inputs)}
        if self._operation == "invert_relation":
            return {"relation": self._invert_relation(call.inputs)}
        if self._operation == "join_relation_subjects":
            return {"relation": self._join_relation_subjects(call.inputs)}
        if self._operation == "select_related_subjects":
            candidates, relation = self._select_related_subjects(call)
            return {"candidates": candidates, "relation": relation}
        if self._operation == "take_candidates":
            return {
                "candidates": self._take_candidates(
                    call.inputs,
                    call.node_parameters,
                )
            }
        return {"candidates": self._intersect_candidates(call.inputs)}

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
        admitted_by_id = {
            entry.candidate_id: entry for entry in call.inputs[port].candidate_data
        }
        return value, {
            candidate.candidate_id: (
                candidate,
                admitted_by_id[candidate.candidate_id],
            )
            for candidate in value.items
        }

    def _relate_by_parent(self, call: OperationCall) -> CandidateRelation:
        subjects, subjects_by_id = self._candidate_references(
            call,
            call.inputs["subjects"].value,
            port="subjects",
        )
        _parents, parents_by_id = self._candidate_references(
            call,
            call.inputs["parents"].value,
            port="parents",
        )
        used_parents: set[str] = set()
        entries: list[CandidateRelationEntry] = []
        for subject in subjects.items:
            if (
                len(subject.parent_ids) != 1
                or subject.parent_ids[0] not in parents_by_id
            ):
                raise ValueError(
                    "each subject must name exactly one supplied parent"
                )
            parent_id = subject.parent_ids[0]
            used_parents.add(parent_id)
            entries.append(
                CandidateRelationEntry(
                    subject=subjects_by_id[subject.candidate_id][1],
                    reference=parents_by_id[parent_id][1],
                )
            )
        if used_parents != set(parents_by_id):
            raise ValueError("subjects do not cover every supplied parent")
        return CandidateRelation(entries)

    def _relate_to_single_reference(
        self,
        call: OperationCall,
    ) -> CandidateRelation:
        subjects, subjects_by_id = self._candidate_references(
            call,
            call.inputs["subjects"].value,
            port="subjects",
        )
        references, references_by_id = self._candidate_references(
            call,
            call.inputs["references"].value,
            port="references",
        )
        if len(references.items) != 1:
            raise ValueError("reference relation requires exactly one reference")
        reference = references_by_id[references.items[0].candidate_id][1]
        return CandidateRelation(tuple(
            CandidateRelationEntry(
                subject=subjects_by_id[subject.candidate_id][1],
                reference=reference,
            )
            for subject in subjects.items
        ))

    @staticmethod
    def _compose_relations(
        inputs: Mapping[str, AdmittedPort],
    ) -> CandidateRelation:
        left = inputs["left_relation"].value
        right = inputs["right_relation"].value
        right_by_subject = {entry.subject: entry.reference for entry in right.entries}
        entries: list[CandidateRelationEntry] = []
        for entry in left.entries:
            reference = right_by_subject.get(entry.reference)
            if reference is None:
                raise ValueError(
                    "every left reference must match one exact right subject"
                )
            entries.append(
                CandidateRelationEntry(
                    subject=entry.subject,
                    reference=reference,
                )
            )
        return CandidateRelation(entries)

    @staticmethod
    def _invert_relation(
        inputs: Mapping[str, AdmittedPort],
    ) -> CandidateRelation:
        return CandidateRelation(tuple(
            CandidateRelationEntry(
                subject=entry.reference,
                reference=entry.subject,
            )
            for entry in inputs["relation"].value.entries
        ))

    @staticmethod
    def _join_relation_subjects(
        inputs: Mapping[str, AdmittedPort],
    ) -> CandidateRelation:
        left = inputs["left_relation"].value
        right = inputs["right_relation"].value
        right_subject_by_reference: dict[
            CandidateDataReference,
            CandidateDataReference,
        ] = {}
        for entry in right.entries:
            if entry.reference in right_subject_by_reference:
                raise ValueError(
                    "right relation must contain one subject per shared reference"
                )
            right_subject_by_reference[entry.reference] = entry.subject
        entries: list[CandidateRelationEntry] = []
        for entry in left.entries:
            reference = right_subject_by_reference.get(entry.reference)
            if reference is None:
                raise ValueError(
                    "every left reference must match one right relation reference"
                )
            entries.append(
                CandidateRelationEntry(
                    subject=entry.subject,
                    reference=reference,
                )
            )
        return CandidateRelation(entries)

    def _select_related_subjects(
        self,
        call: OperationCall,
    ) -> tuple[CandidateCollection, CandidateRelation]:
        subjects, subjects_by_id = self._candidate_references(
            call,
            call.inputs["subjects"].value,
            port="subjects",
        )
        selected_references = set(
            call.inputs["selected_references"].candidate_data
        )
        subject_references = {
            reference for _candidate, reference in subjects_by_id.values()
        }
        relation_entries = call.inputs["relation"].value.entries
        if {entry.subject for entry in relation_entries} != subject_references:
            raise ValueError(
                "relation subjects must exactly cover the supplied subjects"
            )
        if not selected_references.issubset(
            {entry.reference for entry in relation_entries}
        ):
            raise ValueError(
                "selected references must occur in the supplied relation"
            )
        selected_entries = tuple(
            entry
            for entry in relation_entries
            if entry.reference in selected_references
        )
        selected_subjects = {entry.subject for entry in selected_entries}
        return (
            CandidateCollection(
                collection_id="collection-ops-selected-related-subjects",
                item_type=subjects.item_type,
                items=tuple(
                    candidate
                    for candidate, reference in subjects_by_id.values()
                    if reference in selected_subjects
                ),
            ),
            CandidateRelation(selected_entries),
        )

    @staticmethod
    def _intersect_candidates(
        inputs: Mapping[str, AdmittedPort],
    ) -> CandidateCollection:
        supplied = [
            inputs[port].value for port in _INTERSECTION_PORTS if port in inputs
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
        return CandidateCollection(
            collection_id="collection-ops-intersected-candidates",
            item_type=first.item_type,
            items=tuple(
                candidate
                for candidate in first.items
                if all(
                    index.get(candidate.candidate_id) == candidate
                    for index in identities[1:]
                )
            ),
        )

    @staticmethod
    def _take_candidates(
        inputs: Mapping[str, AdmittedPort],
        node_parameters: Mapping[str, Any],
    ) -> CandidateCollection:
        candidates = inputs["candidates"].value
        k = node_parameters["k"]
        if k > len(candidates.items):
            raise ValueError("k cannot exceed Candidate input cardinality")
        return CandidateCollection(
            collection_id=f"{candidates.collection_id}-first-{k}",
            item_type=candidates.item_type,
            items=list(candidates.items[:k]),
        )

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
    def _concat_relations(
        inputs: Mapping[str, AdmittedPort],
    ) -> CandidateRelation:
        entries: list[CandidateRelationEntry] = []
        subject_sources: dict[CandidateDataReference, str] = {}
        for port in _RELATION_PORTS:
            if port not in inputs:
                continue
            for entry in inputs[port].value.entries:
                previous = subject_sources.get(entry.subject)
                if previous is not None:
                    raise ValueError(
                        "Candidate relation subject occurs in more than one "
                        f"input partition: {previous}, {port}"
                    )
                subject_sources[entry.subject] = port
                entries.append(entry)
        return CandidateRelation(entries)
