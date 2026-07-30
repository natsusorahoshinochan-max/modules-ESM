"""Typed SoluProt execution for the cohesive solubility package."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datatypes import (
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
    invoke_soluprot,
    parse_soluprot_output,
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
