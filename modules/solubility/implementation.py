"""Canonical sequence-solubility Scientific Operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from core import OperationCall, ResolvedProducedObservation
from datatypes import (
    CalibrationObservationContext,
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ScoreCollection,
    ScoreObservation,
)

from .adapter import (
    LocalProteinSolAdapter,
    LocalSoluProtAdapter,
)


_CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
_PredictionT = TypeVar("_PredictionT")


def _sequence_subjects(
    call: OperationCall,
) -> tuple[tuple[Candidate, CandidateDataReference], ...]:
    """Project one complete admitted sequence-subject population."""
    collection = cast(
        CandidateCollection,
        call.inputs["sequence_candidates"].value,
    )
    references = call.inputs["sequence_candidates"].candidate_data
    return tuple(
        zip(collection.items, references, strict=True)
    )


def _method_sequences(
    subjects: tuple[tuple[Candidate, CandidateDataReference], ...],
    *,
    provider_name: str,
    minimum_length: int,
) -> tuple[ProteinSequence, ...]:
    """Admit one Method's exact sequence population before Provider entry."""
    sequences = tuple(
        cast(ProteinSequence, candidate.data)
        for candidate, _ in subjects
    )
    if not sequences or any(
        len(sequence.sequence) < minimum_length
        or not set(sequence.sequence) <= _CANONICAL_AMINO_ACIDS
        for sequence in sequences
    ):
        raise ValueError(
            f"{provider_name} requires canonical protein sequences of at "
            f"least {minimum_length} residues"
        )
    return sequences


def _associate_predictions(
    subjects: tuple[tuple[Candidate, CandidateDataReference], ...],
    predictions: tuple[_PredictionT, ...],
) -> tuple[tuple[Candidate, CandidateDataReference, _PredictionT], ...]:
    """Associate Adapter-aligned predictions with admitted subjects."""
    return tuple(
        (candidate, reference, prediction)
        for (candidate, reference), prediction in zip(
            subjects,
            predictions,
            strict=True,
        )
    )


class SoluProtImplementation:
    """Emit one formal intrinsic Observation for every exact subject."""

    def __init__(
        self,
        *,
        adapter: LocalSoluProtAdapter,
        method: ExactContractReference,
        produced_observation: ResolvedProducedObservation,
    ) -> None:
        self._adapter = adapter
        self._method = method
        self._produced_observation = produced_observation

    def execute(self, call: OperationCall) -> dict[str, Any]:
        subjects = _sequence_subjects(call)
        sequences = _method_sequences(
            subjects,
            provider_name="SoluProt",
            minimum_length=20,
        )
        predictions = self._adapter.predict(sequences)
        produced = self._produced_observation
        joined = _associate_predictions(subjects, predictions)
        observations = [
            ScoreObservation(
                subject=reference,
                metric=produced.metric,
                method=self._method,
                context=IntrinsicObservationContext(),
                value=prediction.soluble_probability,
                residue_axis=None,
                source_partition=produced.output_partition,
            )
            for _, reference, prediction in joined
        ]
        return {
            "scores": ScoreCollection(
                (
                    produced.output_partition.replace("_", "-", 1)
                    + "-observations"
                ),
                observations,
            )
        }


class ProteinSolImplementation:
    """Emit the closed calibrated three-Metric Protein-Sol result."""

    def __init__(
        self,
        *,
        adapter: LocalProteinSolAdapter,
        method: ExactContractReference,
        produced_observations: tuple[ResolvedProducedObservation, ...],
    ) -> None:
        self._adapter = adapter
        self._method = method
        self._produced_observations = produced_observations

    def _observation_definitions(
        self,
    ) -> Mapping[str, ResolvedProducedObservation]:
        return {
            observation.output_partition: observation
            for observation in self._produced_observations
            if observation.output_port == "scores"
        }

    @staticmethod
    def _observation_context(
        produced: ResolvedProducedObservation,
    ) -> IntrinsicObservationContext | CalibrationObservationContext:
        profile = produced.context_profile
        if produced.output_partition == "protein_sol_pi":
            return IntrinsicObservationContext()
        return CalibrationObservationContext(
            calibration_metric=str(profile["calibration_metric"]),
            calibration_value=float(profile["calibration_value"]),
            calibration_unit=str(profile["calibration_unit"]),
            population_id=str(profile["population_id"]),
        )

    def execute(self, call: OperationCall) -> dict[str, Any]:
        subjects = _sequence_subjects(call)
        sequences = _method_sequences(
            subjects,
            provider_name="Protein-Sol",
            minimum_length=21,
        )
        predictions = self._adapter.predict(sequences)
        produced = self._observation_definitions()
        observations: list[ScoreObservation] = []
        for _, reference, prediction in _associate_predictions(
            subjects,
            predictions,
        ):
            values = (
                (
                    "protein_sol_percent",
                    prediction.percent_soluble_fraction,
                ),
                (
                    "protein_sol_scaled",
                    prediction.scaled_soluble_fraction,
                ),
                ("protein_sol_pi", prediction.isoelectric_point),
            )
            for partition, value in values:
                observation = produced[partition]
                observations.append(
                    ScoreObservation(
                        subject=reference,
                        metric=observation.metric,
                        method=self._method,
                        context=self._observation_context(observation),
                        value=value,
                        residue_axis=None,
                        source_partition=observation.output_partition,
                    )
                )
        return {
            "scores": ScoreCollection(
                "protein-sol-observations",
                observations,
            )
        }
