"""Direct collection operations over exact v2 domain values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.port_types import CatalogBuildError, canonical_json_bytes
from datatypes import (
    Candidate,
    CandidateCollection,
    PairwiseCandidateMapping,
    PairwiseCandidateMatch,
    Score,
    ScoreCollection,
    ScoreObservation,
)


_CANDIDATE_PORTS = ("candidates_a", "candidates_b", "candidates_c")
_SCORE_PORTS = ("scores_a", "scores_b", "scores_c")


class CollectionOpsImplementation:
    """Execute one deterministic, identity-preserving collection operation."""

    def __init__(self, operation: str, catalog: Any | None = None) -> None:
        self._operation = operation
        self._catalog = catalog

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if binding_parameters:
            raise ValueError(
                "collection operations do not accept Binding parameters"
            )
        if self._operation == "concat_candidates":
            self._require_no_node_parameters(node_parameters)
            return {"candidates": self._concat_candidates(inputs)}
        if self._operation == "merge_scores":
            self._require_no_node_parameters(node_parameters)
            return {"scores": self._merge_scores(inputs)}
        if self._operation == "rebind_candidate_pairing":
            self._require_no_node_parameters(node_parameters)
            return {"pairing": self._rebind_candidate_pairing(inputs)}
        if self._operation == "take_candidates":
            return {
                "candidates": self._take_candidates(
                    inputs,
                    node_parameters,
                )
            }
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

    def _candidate_digests(
        self,
        value: object,
        *,
        port: str,
    ) -> tuple[CandidateCollection, dict[str, tuple[Candidate, str]]]:
        if (
            self._catalog is None
            or type(value) is not CandidateCollection
            or not value.items
        ):
            raise ValueError(f"{port} must be a non-empty Candidate Collection")
        codec = self._catalog.require_port_type(value.item_type, "2.0.0")
        by_id: dict[str, tuple[Candidate, str]] = {}
        for candidate in value.items:
            if (
                type(candidate) is not Candidate
                or not candidate.candidate_id
                or candidate.candidate_id in by_id
            ):
                raise ValueError(
                    f"{port} contains incomplete or duplicate Candidates"
                )
            by_id[candidate.candidate_id] = (
                candidate,
                codec.content_digest(candidate.data),
            )
        return value, by_id

    def _rebind_candidate_pairing(
        self,
        inputs: Mapping[str, Any],
    ) -> PairwiseCandidateMapping:
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
        subjects, subjects_by_id = self._candidate_digests(
            inputs["subjects"],
            port="subjects",
        )
        parents, parents_by_id = self._candidate_digests(
            inputs["parents"],
            port="parents",
        )
        references, references_by_id = self._candidate_digests(
            inputs["references"],
            port="references",
        )
        pairing = inputs["parent_pairing"]
        if type(pairing) is not PairwiseCandidateMapping:
            raise ValueError("parent_pairing must be an exact Candidate pairing")
        parent_to_reference: dict[str, tuple[str, str]] = {}
        seen_references: set[str] = set()
        for entry in pairing.entries:
            parent = parents_by_id.get(entry.subject_candidate_id)
            reference = references_by_id.get(entry.reference_candidate_id)
            if (
                parent is None
                or reference is None
                or parent[1] != entry.subject_content_digest
                or reference[1] != entry.reference_content_digest
                or entry.subject_candidate_id in parent_to_reference
                or entry.reference_candidate_id in seen_references
            ):
                raise ValueError(
                    "parent_pairing contradicts exact Candidate identities "
                    "or content"
                )
            parent_to_reference[entry.subject_candidate_id] = (
                entry.reference_candidate_id,
                entry.reference_content_digest,
            )
            seen_references.add(entry.reference_candidate_id)
        if set(parent_to_reference) != set(parents_by_id):
            raise ValueError("parent_pairing is not complete for all parents")
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
            reference_id, reference_digest = parent_to_reference[parent_id]
            if parent_id in used_parents or reference_id in used_references:
                raise ValueError(
                    "pairing rebinding requires one subject per exact parent"
                )
            used_parents.add(parent_id)
            used_references.add(reference_id)
            rebound.append(PairwiseCandidateMatch(
                subject_candidate_id=subject.candidate_id,
                subject_content_digest=subjects_by_id[
                    subject.candidate_id
                ][1],
                reference_candidate_id=reference_id,
                reference_content_digest=reference_digest,
            ))
        if used_parents != set(parents_by_id):
            raise ValueError("subjects do not cover every exact parent")
        return PairwiseCandidateMapping(rebound)

    @staticmethod
    def _concat_candidates(
        inputs: Mapping[str, Any],
    ) -> CandidateCollection:
        supplied = [
            (port, inputs[port])
            for port in _CANDIDATE_PORTS
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
                if isinstance(entry, Score):
                    raise ValueError(
                        "Score merge does not accept legacy subject-free scores"
                    )
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
