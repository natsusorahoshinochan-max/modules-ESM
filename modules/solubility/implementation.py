"""Typed SoluProt execution for the cohesive solubility package."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
    SoluProtMode,
    invoke_protein_sol,
    invoke_soluprot,
    parse_protein_sol_output,
    parse_soluprot_output,
    validate_protein_sol_environment,
    validate_protein_sol_sequences,
    validate_soluprot_environment,
    validate_sequences,
)


class SoluProtImplementation:
    """Emit one formal intrinsic Observation for every exact subject."""

    def __init__(
        self,
        run_resources: Any,
        environment: Mapping[str, Any],
        catalog: Any,
        *,
        mode: SoluProtMode,
    ) -> None:
        self._run_resources = run_resources
        self._environment = environment
        self._catalog = catalog
        self._mode = mode

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
        sequences: list[str] = []
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
            sequences.append(candidate.data.sequence)
        validate_sequences(sequences)
        return subjects

    def _reference(
        self,
        kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        contract = self._catalog.require_contract(
            kind,
            contract_id,
            "2.0.0",
        )
        return ExactContractReference(**contract.reference())

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters:
            raise ValueError("SoluProt accepts no Workflow model selection")
        subjects = self._subjects(inputs)
        sequences = [
            candidate.data.sequence
            for candidate in subjects
            if isinstance(candidate.data, ProteinSequence)
        ]
        resolved_environment = validate_soluprot_environment(
            self._environment,
            mode=self._mode,
        )
        runtime_fingerprint = resolved_environment[
            "resolved_runtime_fingerprint"
        ]
        with self._run_resources.temporary_directory(
            prefix=f"soluprot-{self._mode}-"
        ) as staging_directory:
            with self._run_resources.engine_invocation(
                engine_role=f"soluprot_{self._mode}",
                engine_identity=(
                    f"soluprot.{self._mode}.v1_1_0/"
                    f"{runtime_fingerprint}"
                ),
            ):
                raw_output = invoke_soluprot(
                    sequences=sequences,
                    mode=self._mode,
                    staging_directory=staging_directory,
                    environment=self._environment,
                    run_resources=self._run_resources,
                    resolved_environment=resolved_environment,
                )
            values = parse_soluprot_output(
                raw_output,
                expected_count=len(subjects),
            )
        method = self._reference(
            "method",
            f"solubility.soluprot_{self._mode}.v1_1_0",
        )
        metric = self._reference(
            "metric",
            "solubility.soluprot_probability",
        )
        observations = [
            ScoreObservation(
                candidate_id=candidate.candidate_id,
                metric=metric,
                method=method,
                context=IntrinsicObservationContext(),
                value=value,
                source_partition=f"soluprot_{self._mode}",
            )
            for candidate, value in zip(subjects, values, strict=True)
        ]
        return {
            "scores": ScoreCollection(
                f"soluprot-{self._mode}-observations",
                observations,
            )
        }


class ProteinSolImplementation:
    """Emit the closed calibrated three-Metric Protein-Sol result."""

    def __init__(
        self,
        run_resources: Any,
        environment: Mapping[str, Any],
        catalog: Any,
    ) -> None:
        self._run_resources = run_resources
        self._environment = environment
        self._catalog = catalog

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
        sequences: list[str] = []
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
            sequences.append(candidate.data.sequence)
        validate_protein_sol_sequences(sequences)
        return subjects

    def _reference(
        self,
        kind: str,
        contract_id: str,
    ) -> ExactContractReference:
        contract = self._catalog.require_contract(
            kind,
            contract_id,
            "2.0.0",
        )
        return ExactContractReference(**contract.reference())

    def execute(
        self,
        *,
        inputs: Mapping[str, Any],
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        if node_parameters or binding_parameters:
            raise ValueError(
                "Protein-Sol accepts no Workflow model or scale selection"
            )
        subjects = self._subjects(inputs)
        sequences = [
            candidate.data.sequence
            for candidate in subjects
            if isinstance(candidate.data, ProteinSequence)
        ]
        resolved = validate_protein_sol_environment(self._environment)
        runtime_fingerprint = resolved["resolved_runtime_fingerprint"]
        with self._run_resources.temporary_directory(
            prefix="protein-sol-"
        ) as staging_directory:
            with self._run_resources.engine_invocation(
                engine_role="protein_sol_sequence_prediction",
                engine_identity=(
                    "protein-sol.sequence-prediction-2017/"
                    f"{runtime_fingerprint}"
                ),
            ):
                raw_output = invoke_protein_sol(
                    sequences=sequences,
                    staging_directory=staging_directory,
                    environment=self._environment,
                    run_resources=self._run_resources,
                    resolved_environment=resolved,
                )
            results = parse_protein_sol_output(
                raw_output,
                expected_count=len(subjects),
            )
        method = self._reference(
            "method",
            "solubility.protein_sol.sequence_prediction_2017",
        )
        metrics = {
            name: self._reference("metric", metric_id)
            for name, metric_id in (
                ("percent_sol", "solubility.protein_sol_percent"),
                ("scaled_sol", "solubility.protein_sol_scaled"),
                ("pi", "solubility.protein_sol_pi"),
            )
        }
        context = CalibrationObservationContext(
            calibration_metric="population_scaled_solubility",
            calibration_value=0.446,
            calibration_unit="dimensionless",
            population_id="niwa_non_membrane_2396",
        )
        observations = [
            ScoreObservation(
                candidate_id=candidate.candidate_id,
                metric=metrics[name],
                method=method,
                context=(
                    IntrinsicObservationContext()
                    if name == "pi"
                    else context
                ),
                value=result[name],
                source_partition=f"protein_sol_{name.removesuffix('_sol')}",
            )
            for candidate, result in zip(subjects, results, strict=True)
            for name in ("percent_sol", "scaled_sol", "pi")
        ]
        return {
            "scores": ScoreCollection(
                "protein-sol-observations",
                observations,
            )
        }
