"""Canonical sequence-solubility Scientific Operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from core.operation import (
    OperationCall,
)
from core.scoring.observation_plan import (
    CalibrationContextProfile,
    IntrinsicContextProfile,
    ResolvedProducedObservation,
)
from datatypes.candidate import CandidateCollection
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import (
    CalibrationObservationContext,
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence

from .adapter import (
    LocalProteinSolAdapter,
    LocalSoluProtAdapter,
    SequenceSolubilitySubject,
)


_CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
def _method_subjects(
    call: OperationCall,
    *,
    provider_name: str,
    minimum_length: int,
) -> tuple[SequenceSolubilitySubject, ...]:
    """Admit one Method's exact sequence-subject population."""
    collection = cast(
        CandidateCollection,
        call.inputs["sequence_candidates"].value,
    )
    references = call.inputs["sequence_candidates"].candidate_data
    references_by_candidate_id = {
        reference.candidate_id: reference for reference in references
    }
    subjects = tuple(
        SequenceSolubilitySubject(
            subject=references_by_candidate_id[candidate.candidate_id],
            sequence=cast(ProteinSequence, candidate.data),
        )
        for candidate in collection.items
    )
    if not subjects or any(
        len(subject.sequence.sequence) < minimum_length
        or not set(subject.sequence.sequence) <= _CANONICAL_AMINO_ACIDS
        for subject in subjects
    ):
        raise ValueError(
            f"{provider_name} requires canonical protein sequences of at "
            f"least {minimum_length} residues"
        )
    return subjects


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
        subjects = _method_subjects(
            call,
            provider_name="SoluProt",
            minimum_length=20,
        )
        predictions = self._adapter.predict(subjects)
        produced = self._produced_observation
        observations = [
            ScoreObservation(
                subject=prediction.subject,
                metric=produced.metric,
                method=self._method,
                context=IntrinsicObservationContext(),
                value=prediction.soluble_probability,
                residue_axis=None,
                source_partition=produced.output_partition,
            )
            for prediction in predictions
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
        if isinstance(profile, IntrinsicContextProfile):
            return IntrinsicObservationContext()
        if not isinstance(profile, CalibrationContextProfile):
            raise TypeError("Protein-Sol requires intrinsic or calibration Context")
        return CalibrationObservationContext(
            calibration_metric=profile.calibration_metric,
            calibration_value=profile.calibration_value,
            calibration_unit=profile.calibration_unit,
            population_id=profile.population_id,
        )

    def execute(self, call: OperationCall) -> dict[str, Any]:
        subjects = _method_subjects(
            call,
            provider_name="Protein-Sol",
            minimum_length=21,
        )
        predictions = self._adapter.predict(subjects)
        produced = self._observation_definitions()
        observations: list[ScoreObservation] = []
        for prediction in predictions:
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
                        subject=prediction.subject,
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
