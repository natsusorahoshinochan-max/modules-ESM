"""Canonical sequence-solubility Scientific Operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, cast

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
    provider_sequence_id,
)


class _KeyedProviderPrediction(Protocol):
    provider_sequence_id: str


_PredictionT = TypeVar(
    "_PredictionT",
    bound=_KeyedProviderPrediction,
)


def _sequence_subjects(
    call: OperationCall,
    *,
    provider_name: str,
) -> tuple[tuple[str, Candidate, CandidateDataReference], ...]:
    """Attach the staging identity to each already-admitted sequence subject."""
    collection = cast(
        CandidateCollection,
        call.inputs["sequence_candidates"].value,
    )
    if collection.item_type != "protein.sequence":
        raise ValueError(f"{provider_name} requires protein.sequence item_type")
    references = call.inputs["sequence_candidates"].candidate_data
    return tuple(
        (provider_sequence_id(index), candidate, reference)
        for index, (candidate, reference) in enumerate(
            zip(collection.items, references)
        )
    )


def _join_provider_predictions(
    subjects: tuple[tuple[str, Candidate, CandidateDataReference], ...],
    predictions: tuple[_PredictionT, ...],
) -> tuple[tuple[Candidate, CandidateDataReference, _PredictionT], ...]:
    """Project conforming Provider rows into staged subject order."""
    predictions_by_provider_id = {
        prediction.provider_sequence_id: prediction
        for prediction in predictions
    }
    return tuple(
        (
            candidate,
            reference,
            predictions_by_provider_id[provider_id],
        )
        for provider_id, candidate, reference in subjects
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
        if call.node_parameters or call.binding_parameters:
            raise ValueError("SoluProt accepts no Workflow model selection")
        subjects = _sequence_subjects(call, provider_name="SoluProt")
        sequences = tuple(
            cast(ProteinSequence, candidate.data)
            for _, candidate, _ in subjects
        )
        predictions = self._adapter.predict(sequences)
        produced = self._produced_observation
        joined = _join_provider_predictions(subjects, predictions)
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
        produced = {
            observation.output_partition: observation
            for observation in self._produced_observations
            if observation.output_port == "scores"
        }
        required = {
            "protein_sol_percent",
            "protein_sol_scaled",
            "protein_sol_pi",
        }
        if set(produced) != required:
            raise RuntimeError(
                "Protein-Sol Binding must resolve its exact three Observations"
            )
        return produced

    @staticmethod
    def _observation_context(
        produced: ResolvedProducedObservation,
    ) -> IntrinsicObservationContext | CalibrationObservationContext:
        profile = produced.context_profile
        if profile["kind"] == "intrinsic":
            return IntrinsicObservationContext()
        if profile["kind"] == "calibration":
            return CalibrationObservationContext(
                calibration_metric=str(profile["calibration_metric"]),
                calibration_value=float(profile["calibration_value"]),
                calibration_unit=str(profile["calibration_unit"]),
                population_id=str(profile["population_id"]),
            )
        raise RuntimeError(
            "Protein-Sol Binding declares an unsupported Observation Context"
        )

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError(
                "Protein-Sol accepts no Workflow model or scale selection"
            )
        subjects = _sequence_subjects(call, provider_name="Protein-Sol")
        sequences = tuple(
            cast(ProteinSequence, candidate.data)
            for _, candidate, _ in subjects
        )
        predictions = self._adapter.predict(sequences)
        produced = self._observation_definitions()
        observations: list[ScoreObservation] = []
        for _, reference, prediction in _join_provider_predictions(
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
