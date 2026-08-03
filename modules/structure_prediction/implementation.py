"""Exact-reference confidence materialization."""

from __future__ import annotations

from collections.abc import Sequence
import math
import re
from typing import Any

from core import OperationCall, ResolvedProducedObservation
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    IntrinsicObservationContext,
    ResidueAxisReference,
    ScoreCollection,
    ScoreObservation,
)

from .domain import ConfidenceFact, ConfidenceFactCollection, prediction_key
from .port_types import (
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
    prediction_axis_reference,
)


_METRICS = frozenset(
    {
        "structure.ptm",
        "structure.plddt.per_residue",
        "structure.plddt.mean_residue",
        "structure.pae",
    }
)
_SAMPLE_SLOT = re.compile(r"^0:(0|[1-9][0-9]*)$")
_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991


class MaterializeConfidenceImplementation:
    """Join subjectless confidence to admitted structure Candidate references."""

    def __init__(
        self,
        *,
        produced_observations: Sequence[ResolvedProducedObservation],
    ) -> None:
        observations = tuple(produced_observations)
        by_metric = {
            observation.metric.contract_id: observation
            for observation in observations
        }
        if (
            len(by_metric) != len(observations)
            or set(by_metric) != _METRICS
            or any(
                observation.output_port != "observations"
                or observation.output_partition != "prediction_confidence"
                for observation in observations
            )
        ):
            raise ValueError(
                "materialize-confidence Binding must resolve its four exact "
                "prediction-confidence Observations"
            )
        self._produced_by_metric = by_metric

    @staticmethod
    def _full_join(
        call: OperationCall,
    ) -> tuple[
        ConfidenceFactCollection,
        tuple[tuple[CandidateDataReference, ConfidenceFact], ...],
    ]:
        if set(call.inputs) != {
            "structure_candidates",
            "confidence_facts",
        }:
            raise ValueError(
                "materialize confidence requires exact structure_candidates "
                "and confidence_facts inputs"
            )
        candidates = call.inputs["structure_candidates"]
        facts = call.inputs["confidence_facts"]
        if (
            type(candidates) is not CandidateCollection
            or candidates.item_type != "protein.structure"
            or not candidates.items
        ):
            raise ValueError(
                "structure_candidates must be a nonempty structure Candidate "
                "Collection"
            )
        if type(facts) is not ConfidenceFactCollection:
            raise ValueError(
                "confidence_facts must be an admitted ConfidenceFactCollection"
            )

        admitted = call.input_content_digests.get("structure_candidates")
        if (
            admitted is None
            or admitted.port_type_id != "candidate.collection"
        ):
            raise ValueError(
                "structure_candidates lack admitted Candidate data references"
            )
        references_by_id: dict[str, CandidateDataReference] = {}
        for reference in admitted.candidate_data:
            if (
                type(reference) is not CandidateDataReference
                or reference.data_type_id != "protein.structure"
                or reference.candidate_id in references_by_id
            ):
                raise ValueError(
                    "structure_candidates admitted references are incomplete "
                    "or duplicate"
                )
            references_by_id[reference.candidate_id] = reference

        candidates_by_key: dict[
            str,
            tuple[Candidate, CandidateDataReference, str, int],
        ] = {}
        candidate_ids: set[str] = set()
        producer_slots: set[tuple[str, int]] = set()
        for candidate in candidates.items:
            if (
                type(candidate) is not Candidate
                or candidate.candidate_id in candidate_ids
            ):
                raise ValueError(
                    "structure_candidates contain duplicate or incomplete "
                    "Candidates"
                )
            candidate_ids.add(candidate.candidate_id)
            reference = references_by_id.get(candidate.candidate_id)
            key = candidate.metadata.get("prediction_key")
            output_port = candidate.metadata.get("output_port")
            sample_slot = candidate.metadata.get("sample_slot")
            slot_match = (
                _SAMPLE_SLOT.fullmatch(sample_slot)
                if type(sample_slot) is str
                else None
            )
            output_slot = (
                int(slot_match.group(1)) if slot_match is not None else -1
            )
            if (
                reference is None
                or type(key) is not str
                or type(output_port) is not str
                or slot_match is None
                or output_slot > _I_JSON_INTEGER_LIMIT
                or key in candidates_by_key
                or (output_port, output_slot) in producer_slots
            ):
                raise ValueError(
                    "every structure Candidate must have unique admitted "
                    "prediction_key, output_port, and canonical 0:index "
                    "sample_slot metadata"
                )
            producer_slots.add((output_port, output_slot))
            candidates_by_key[key] = (
                candidate,
                reference,
                output_port,
                output_slot,
            )
        if candidate_ids != set(references_by_id):
            raise ValueError(
                "structure Candidate values and admitted references do not "
                "form one complete set"
            )

        facts_by_key = {fact.prediction_key: fact for fact in facts.entries}
        if set(candidates_by_key) != set(facts_by_key):
            raise ValueError(
                "structure Candidates and confidence facts do not form one "
                "complete prediction-key set"
            )

        joined: list[tuple[CandidateDataReference, ConfidenceFact]] = []
        for candidate in candidates.items:
            key = candidate.metadata["prediction_key"]
            assert type(key) is str
            _, reference, output_port, output_slot = candidates_by_key[key]
            fact = facts_by_key[key]
            if reference.content_digest != fact.structure_content_digest:
                raise ValueError(
                    "confidence fact structure digest contradicts admitted "
                    "Candidate content"
                )
            expected_key = prediction_key(
                output_role=output_port,
                output_slot=output_slot,
                structure_content_digest=reference.content_digest,
                prediction_axis_content_digest=(
                    PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(
                        fact.prediction_axis
                    )
                ),
            )
            if key != expected_key:
                raise ValueError(
                    "prediction_key does not bind the canonical output slot, "
                    "admitted structure content, and prediction axis"
                )
            joined.append((reference, fact))
        return facts, tuple(joined)

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError(
                "materialize confidence accepts no Node or Binding parameters"
            )

        facts, joined = self._full_join(call)
        observations: list[ScoreObservation] = []
        for subject, fact in joined:
            axis = prediction_axis_reference(fact.prediction_axis)
            non_null_plddt = tuple(
                value
                for value in fact.plddt_per_residue
                if value is not None
            )
            values: tuple[
                tuple[str, object, ResidueAxisReference | None], ...
            ] = (
                (
                    "structure.plddt.per_residue",
                    list(fact.plddt_per_residue),
                    axis,
                ),
                (
                    "structure.plddt.mean_residue",
                    math.fsum(non_null_plddt) / len(non_null_plddt),
                    axis,
                ),
            )
            if fact.ptm is not None:
                values += (("structure.ptm", fact.ptm, None),)
            if fact.pae is not None:
                values += (
                    (
                        "structure.pae",
                        [list(row) for row in fact.pae],
                        axis,
                    ),
                )
            for metric_id, value, residue_axis in values:
                produced = self._produced_by_metric[metric_id]
                observations.append(
                    ScoreObservation(
                        subject=subject,
                        metric=produced.metric,
                        method=facts.observation_method,
                        context=IntrinsicObservationContext(),
                        value=value,
                        residue_axis=residue_axis,
                        source_partition=produced.output_partition,
                    )
                )

        return {
            "observations": ScoreCollection(
                collection_id="structure-prediction-confidence",
                entries=tuple(observations),
            )
        }


__all__ = ["MaterializeConfidenceImplementation"]
