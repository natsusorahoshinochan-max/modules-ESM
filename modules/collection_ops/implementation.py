"""Direct collection operations over exact v2 domain values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.port_types import CatalogBuildError, canonical_json_bytes
from datatypes import (
    Candidate,
    CandidateCollection,
    Score,
    ScoreCollection,
    ScoreObservation,
)


_CANDIDATE_PORTS = ("candidates_a", "candidates_b", "candidates_c")
_SCORE_PORTS = ("scores_a", "scores_b", "scores_c")


class CollectionOpsImplementation:
    """Execute one deterministic, identity-preserving collection operation."""

    def __init__(self, operation: str) -> None:
        self._operation = operation

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters:
            raise ValueError("collection operations do not accept parameters")
        if self._operation == "concat_candidates":
            return {"candidates": self._concat_candidates(inputs)}
        if self._operation == "merge_scores":
            return {"scores": self._merge_scores(inputs)}
        raise RuntimeError("unknown collection operation")

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
