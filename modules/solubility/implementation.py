"""Canonical sequence-solubility Scientific Operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from core import OperationCall, ResolvedProducedObservation
from datatypes import (
    CalibrationObservationContext,
    Candidate,
    CandidateCollection,
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

    @staticmethod
    def _subjects(inputs: Mapping[str, Any]) -> list[Candidate]:
        if set(inputs) != {"sequence_candidates"}:
            raise ValueError(
                "SoluProt requires one exact sequence Candidate collection"
            )
        collection = inputs["sequence_candidates"]
        if (
            type(collection) is not CandidateCollection
            or collection.item_type != "protein.sequence"
            or not collection.items
        ):
            raise ValueError(
                "SoluProt requires a non-empty protein sequence Candidate collection"
            )
        candidate_ids: set[str] = set()
        subjects: list[Candidate] = []
        for candidate in collection.items:
            if (
                type(candidate) is not Candidate
                or not candidate.candidate_id
                or candidate.candidate_id in candidate_ids
                or type(candidate.data) is not ProteinSequence
            ):
                raise ValueError(
                    "SoluProt subjects are incomplete or duplicated"
                )
            candidate_ids.add(candidate.candidate_id)
            subjects.append(candidate)
        return subjects

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError("SoluProt accepts no Workflow model selection")
        subjects = self._subjects(call.inputs)
        sequences = tuple(
            cast(ProteinSequence, candidate.data)
            for candidate in subjects
        )
        predictions = self._adapter.predict(sequences)
        produced = self._produced_observation
        observations = [
            ScoreObservation(
                candidate_id=candidate.candidate_id,
                metric=produced.metric,
                method=self._method,
                context=IntrinsicObservationContext(),
                value=prediction,
                source_partition=produced.output_partition,
            )
            for candidate, prediction in zip(
                subjects,
                predictions,
                strict=True,
            )
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

    @staticmethod
    def _subjects(inputs: Mapping[str, Any]) -> list[Candidate]:
        if set(inputs) != {"sequence_candidates"}:
            raise ValueError(
                "Protein-Sol requires one exact sequence Candidate collection"
            )
        collection = inputs["sequence_candidates"]
        if (
            type(collection) is not CandidateCollection
            or collection.item_type != "protein.sequence"
            or not collection.items
        ):
            raise ValueError(
                "Protein-Sol requires a non-empty protein sequence "
                "Candidate collection"
            )
        candidate_ids: set[str] = set()
        subjects: list[Candidate] = []
        for candidate in collection.items:
            if (
                type(candidate) is not Candidate
                or not candidate.candidate_id
                or candidate.candidate_id in candidate_ids
                or type(candidate.data) is not ProteinSequence
            ):
                raise ValueError(
                    "Protein-Sol subjects are incomplete or duplicated"
                )
            candidate_ids.add(candidate.candidate_id)
            subjects.append(candidate)
        return subjects

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
        *,
        population_scaled_solubility: float,
    ) -> IntrinsicObservationContext | CalibrationObservationContext:
        profile = produced.context_profile
        if profile["kind"] == "intrinsic":
            return IntrinsicObservationContext()
        if profile["kind"] == "calibration":
            if (
                float(profile["calibration_value"])
                != population_scaled_solubility
            ):
                raise RuntimeError(
                    "Protein-Sol prediction and Binding calibration conflict"
                )
            return CalibrationObservationContext(
                calibration_metric=str(profile["calibration_metric"]),
                calibration_value=population_scaled_solubility,
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
        subjects = self._subjects(call.inputs)
        sequences = tuple(
            cast(ProteinSequence, candidate.data)
            for candidate in subjects
        )
        predictions = self._adapter.predict(sequences)
        produced = self._observation_definitions()
        observations: list[ScoreObservation] = []
        for candidate, prediction in zip(
            subjects,
            predictions,
            strict=True,
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
                        candidate_id=candidate.candidate_id,
                        metric=observation.metric,
                        method=self._method,
                        context=self._observation_context(
                            observation,
                            population_scaled_solubility=(
                                prediction.population_scaled_solubility
                            ),
                        ),
                        value=value,
                        source_partition=observation.output_partition,
                    )
                )
        return {
            "scores": ScoreCollection(
                "protein-sol-observations",
                observations,
            )
        }
