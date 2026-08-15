"""Direct collection operations over exact v2 domain values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.operation import OperationCall
from core.port_types import CatalogBuildError, canonical_json_bytes
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    ScoreCollection,
    ScoreObservation,
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


class CollectionOpsImplementation:
    """Execute one deterministic, identity-preserving collection operation."""

    def __init__(self, operation: str) -> None:
        self._operation = operation

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.binding_parameters:
            raise ValueError(
                "collection operations do not accept Binding parameters"
            )
        if self._operation == "concat_candidates":
            self._require_no_node_parameters(call.node_parameters)
            return {"candidates": self._concat_candidates(call.inputs)}
        if self._operation == "merge_scores":
            self._require_no_node_parameters(call.node_parameters)
            return {"scores": self._merge_scores(call.inputs)}
        if self._operation == "rebind_candidate_pairing":
            self._require_no_node_parameters(call.node_parameters)
            return {"pairing": self._rebind_candidate_pairing(call)}
        if self._operation == "pair_siblings_by_parent":
            self._require_no_node_parameters(call.node_parameters)
            return {"pairing": self._pair_siblings_by_parent(call)}
        if self._operation == "take_candidates":
            return {
                "candidates": self._take_candidates(
                    call.inputs,
                    call.node_parameters,
                )
            }
        if self._operation == "select_children_by_parent":
            self._require_no_node_parameters(call.node_parameters)
            return {
                "candidates": self._select_children_by_parent(call.inputs)
            }
        if self._operation == "intersect_candidates":
            self._require_no_node_parameters(call.node_parameters)
            return {"candidates": self._intersect_candidates(call.inputs)}
        raise RuntimeError("unknown collection operation")

    @staticmethod
    def _require_no_node_parameters(
        node_parameters: Mapping[str, Any],
    ) -> None:
        if node_parameters:
            raise ValueError(
                "this collection operation does not accept Node parameters"
            )

    @staticmethod
    def _select_children_by_parent(
        inputs: Mapping[str, Any],
    ) -> CandidateCollection:
        if set(inputs) != {"candidates", "parents"}:
            raise ValueError(
                "child selection requires exact candidates and parents inputs"
            )
        candidates = inputs["candidates"]
        parents = inputs["parents"]
        if (
            type(candidates) is not CandidateCollection
            or type(parents) is not CandidateCollection
        ):
            raise ValueError("child selection inputs must be Candidate Collections")
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
        inputs: Mapping[str, Any],
    ) -> CandidateCollection:
        supplied = [
            inputs[port] for port in _INTERSECTION_PORTS if port in inputs
        ]
        if len(supplied) < 2:
            raise ValueError(
                "Candidate intersection requires at least two connected inputs"
            )
        if any(type(value) is not CandidateCollection for value in supplied):
            raise ValueError(
                "Candidate intersection inputs must be Candidate Collections"
            )
        first = supplied[0]
        assert type(first) is CandidateCollection
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
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
    ) -> CandidateCollection:
        if set(inputs) != {"candidates"}:
            raise ValueError(
                "Candidate prefix selection requires one exact candidates input"
            )
        if set(node_parameters) != {"k"}:
            raise ValueError(
                "Candidate prefix selection requires exactly the k Node "
                "parameter"
            )
        candidates = inputs["candidates"]
        k = node_parameters["k"]
        if type(candidates) is not CandidateCollection:
            raise ValueError("candidates must be an exact Candidate Collection")
        if type(k) is not int or k < 1:
            raise ValueError("k must be a positive integer")
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
        value: object,
        *,
        port: str,
    ) -> tuple[
        CandidateCollection,
        dict[str, tuple[Candidate, CandidateDataReference]],
    ]:
        if type(value) is not CandidateCollection or not value.items:
            raise ValueError(f"{port} must be a non-empty Candidate Collection")
        admitted = call.input_content_digests.get(port)
        if admitted is None:
            raise ValueError(f"{port} has no admitted Candidate content identity")
        admitted_by_id = {
            entry.candidate_id: entry
            for entry in admitted.candidate_data
        }
        if len(admitted_by_id) != len(admitted.candidate_data):
            raise ValueError(f"{port} has duplicate admitted Candidate identities")
        by_id: dict[str, tuple[Candidate, CandidateDataReference]] = {}
        for candidate in value.items:
            if (
                type(candidate) is not Candidate
                or not candidate.candidate_id
                or candidate.candidate_id in by_id
            ):
                raise ValueError(
                    f"{port} contains incomplete or duplicate Candidates"
                )
            reference = admitted_by_id.get(candidate.candidate_id)
            if reference is None:
                raise ValueError(
                    f"{port} Candidate content identity was not admitted"
                )
            by_id[candidate.candidate_id] = (
                candidate,
                reference,
            )
        if set(admitted_by_id) != set(by_id):
            raise ValueError(
                f"{port} admitted Candidate identities do not match the input"
            )
        return value, by_id

    def _rebind_candidate_pairing(
        self,
        call: OperationCall,
    ) -> PairwiseCandidateMapping:
        inputs = call.inputs
        if set(inputs) != {
            "subjects",
            "parents",
            "references",
            "parent_pairing",
        }:
            raise ValueError(
                "pairing rebinding requires exact subject, parent, reference, "
                "and parent_pairing inputs"
            )
        subjects, subjects_by_id = self._candidate_references(
            call,
            inputs["subjects"],
            port="subjects",
        )
        parents, parents_by_id = self._candidate_references(
            call,
            inputs["parents"],
            port="parents",
        )
        references, references_by_id = self._candidate_references(
            call,
            inputs["references"],
            port="references",
        )
        pairing = inputs["parent_pairing"]
        if type(pairing) is not PairwiseCandidateMapping:
            raise ValueError("parent_pairing must be an exact Candidate pairing")
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
        if set(inputs) != {"subjects", "references"}:
            raise ValueError(
                "sibling pairing requires exact subject and reference inputs"
            )
        subjects, subjects_by_id = self._candidate_references(
            call,
            inputs["subjects"],
            port="subjects",
        )
        references, references_by_id = self._candidate_references(
            call,
            inputs["references"],
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
        inputs: Mapping[str, Any],
    ) -> CandidateCollection:
        supplied = [
            (port, inputs[port])
            for port in _CONCAT_CANDIDATE_PORTS
            if port in inputs
        ]
        if not supplied:
            raise ValueError(
                "Candidate concatenation requires at least one connected "
                "collection"
            )
        item_type: str | None = None
        candidates: list[Candidate] = []
        source_by_identity: dict[str, str] = {}
        for port, collection in supplied:
            if type(collection) is not CandidateCollection:
                raise ValueError(f"{port} is not a Candidate Collection")
            if item_type is None:
                item_type = collection.item_type
            elif collection.item_type != item_type:
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
        assert item_type is not None
        return CandidateCollection(
            collection_id="collection-ops-concatenated-candidates",
            item_type=item_type,
            items=candidates,
        )

    @staticmethod
    def _merge_scores(inputs: Mapping[str, Any]) -> ScoreCollection:
        supplied = [
            (port, inputs[port])
            for port in _SCORE_PORTS
            if port in inputs
        ]
        if not supplied:
            raise ValueError(
                "Score merge requires at least one connected collection"
            )
        observations: dict[
            tuple[object, ...],
            tuple[ScoreObservation, bytes],
        ] = {}
        for port, collection in supplied:
            if type(collection) is not ScoreCollection:
                raise ValueError(f"{port} is not a Score Collection")
            for entry in collection.entries:
                if type(entry) is not ScoreObservation:
                    raise ValueError(
                        "Score merge requires exact typed Observations"
                    )
                try:
                    encoded_value = canonical_json_bytes(entry.value)
                except CatalogBuildError as error:
                    raise ValueError(
                        "Observation value must be canonical I-JSON"
                    ) from error
                existing = observations.get(entry.identity)
                if existing is None:
                    observations[entry.identity] = (entry, encoded_value)
                    continue
                previous, previous_value = existing
                if previous.source_partition != entry.source_partition:
                    raise ValueError(
                        "Observation identity has a source partition collision"
                    )
                if previous_value != encoded_value:
                    raise ValueError(
                        "Observation identity has conflicting values"
                    )
        return ScoreCollection(
            collection_id="collection-ops-merged-scores",
            entries=[
                observation
                for observation, _ in observations.values()
            ],
        )
