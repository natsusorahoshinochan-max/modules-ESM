"""Canonical folding Operations behind provider-independent Adapter DTOs."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import math
from typing import Any

from core.operation import (
    OperationCall,
    ResolvedProducedObservation,
)
from datatypes import (
    Candidate,
    CandidateDataReference,
    ExactContractReference,
    IntrinsicObservationContext,
    ResidueAxisReference,
    ResolvedStructureResidueAxis,
    ScoreCollection,
    ScoreObservation,
)
from ._output_construction import (
    CompletedFoldingSample,
    CompletedFoldingSampleBatch,
    FoldingOutputConstruction,
)
from .adapter import (
    ESMFold2Adapter,
)
from .simplefold_adapter import (
    SimpleFoldAdapter,
)
from .simplefold_confidence_adapter import (
    SimpleFoldConfidenceAdapter,
)


class ESMFold2FoldingImplementation:
    """Fold sequence Candidates through exactly one selected Binding."""

    def __init__(
        self,
        *,
        adapter: ESMFold2Adapter,
        method: ExactContractReference,
    ) -> None:
        self._adapter = adapter
        self._method = method

    @staticmethod
    def _call_seed(
        effective_seed: int,
        parent_content_digest: str,
        parent_index: int,
        sample_index: int,
    ) -> int:
        digest = hashlib.sha256(
            (
                "protein-workbench-esmfold2-call/v3\0"
                f"{effective_seed}\0{parent_content_digest}\0"
                f"{parent_index}\0{sample_index}"
            ).encode()
        ).digest()
        return int.from_bytes(digest[:4], "big")

    def execute(self, call: OperationCall) -> dict[str, Any]:
        effective_seed = call.node_parameters["effective_seed"]
        sample_count = call.node_parameters["num_samples"]
        construction = FoldingOutputConstruction(
            parent_record=call.inputs["sequence_candidates"],
            sample_count=sample_count,
            observation_method=self._method,
        )

        completed_samples: list[CompletedFoldingSample] = []
        for parent in construction.parents:
            for sample_index in range(sample_count):
                call_seed = self._call_seed(
                    effective_seed,
                    parent.reference.content_digest,
                    parent.slot,
                    sample_index,
                )
                adapter_result = self._adapter.fold(
                    sequence=parent.sequence,
                    derived_call_seed=call_seed,
                    engine_role=(
                        f"fold_parent_{parent.slot}_sample_{sample_index}"
                    ),
                )
                completed_samples.append(
                    CompletedFoldingSample(
                        parent_slot=parent.slot,
                        sample_slot=sample_index,
                        structure=adapter_result.structure,
                        per_residue_plddt=(
                            adapter_result.confidence.per_residue_plddt
                        ),
                        ptm=adapter_result.confidence.ptm,
                        pae=adapter_result.confidence.pae,
                        effective_call_seed=(
                            adapter_result.effective_call_seed
                        ),
                    )
                )
        return construction.construct(
            CompletedFoldingSampleBatch(tuple(completed_samples))
        )


class SimpleFoldFoldingImplementation:
    """Fold sequence Candidates through the exact local SimpleFold Binding."""

    def __init__(
        self,
        *,
        adapter: SimpleFoldAdapter,
        method: ExactContractReference,
    ) -> None:
        self._adapter = adapter
        self._method = method

    @staticmethod
    def _call_seed(
        effective_seed: int,
        parent_content_digest: str,
        parent_index: int,
    ) -> int:
        digest = hashlib.sha256(
            (
                "protein-workbench-simplefold-call/v2\0"
                f"{effective_seed}\0{parent_content_digest}\0{parent_index}"
            ).encode()
        ).digest()
        return int.from_bytes(digest[:7], "big") % 9_007_199_254_740_992

    def execute(self, call: OperationCall) -> dict[str, Any]:
        effective_seed = call.node_parameters["effective_seed"]
        sample_count = call.node_parameters["num_samples"]
        num_steps = call.binding_parameters["num_steps"]
        construction = FoldingOutputConstruction(
            parent_record=call.inputs["sequence_candidates"],
            sample_count=sample_count,
            observation_method=self._method,
        )
        completed_samples: list[CompletedFoldingSample] = []
        for parent in construction.parents:
            call_seed = self._call_seed(
                effective_seed,
                parent.reference.content_digest,
                parent.slot,
            )
            adapter_result = self._adapter.fold(
                sequence=parent.sequence,
                num_steps=num_steps,
                num_samples=sample_count,
                derived_call_seed=call_seed,
                engine_role=f"fold_parent_{parent.slot}",
            )
            for sample in adapter_result.samples:
                completed_samples.append(
                    CompletedFoldingSample(
                        parent_slot=parent.slot,
                        sample_slot=sample.sample_index,
                        structure=sample.structure,
                        per_residue_plddt=sample.per_residue_plddt,
                        effective_call_seed=(
                            adapter_result.effective_call_seed
                        ),
                        num_steps=num_steps,
                    )
                )
        return construction.construct(
            CompletedFoldingSampleBatch(tuple(completed_samples))
        )


class SimpleFoldConfidenceImplementation:
    """Evaluate supplied structures through the fixed confidence-only Method."""

    def __init__(
        self,
        *,
        adapter: SimpleFoldConfidenceAdapter,
        method: ExactContractReference,
        produced_observations: Sequence[ResolvedProducedObservation],
    ) -> None:
        self._adapter = adapter
        self._method = method
        self._produced_observations = {
            observation.metric.contract_id: observation
            for observation in produced_observations
        }

    @staticmethod
    def _structure_candidates_with_axes(
        call: OperationCall,
    ) -> tuple[
        tuple[
            Candidate,
            CandidateDataReference,
            ResolvedStructureResidueAxis,
            ResidueAxisReference,
        ],
        ...,
    ]:
        if set(call.inputs) != {
            "structure_candidates",
            "structure_residue_axes",
        }:
            raise ValueError(
                "SimpleFold confidence requires exact structure Candidates "
                "and resolved axes"
            )
        collection = call.inputs["structure_candidates"].value
        associations = call.inputs["structure_residue_axes"].value
        admitted = call.inputs.get("structure_candidates")
        if collection.item_type != "protein.structure" or not collection.items:
            raise ValueError(
                "SimpleFold confidence requires exact structure Candidates "
                "and resolved axes"
            )

        candidates_by_id: dict[str, Candidate] = {}
        for candidate in collection.items:
            if candidate.candidate_id in candidates_by_id:
                raise ValueError(
                    "SimpleFold confidence structure Candidates are "
                    "incomplete or duplicate"
                )
            candidates_by_id[candidate.candidate_id] = candidate

        references_by_id = {
            reference.candidate_id: reference
            for reference in admitted.candidate_data
        }

        axes_by_reference = {
            entry.subject: entry.residue_axis
            for entry in associations.entries
        }
        if set(axes_by_reference) != set(references_by_id.values()):
            raise ValueError(
                "SimpleFold confidence resolved axes must cover exact "
                "structure references"
            )

        admitted_axes_by_reference = {
            axis.source: axis
            for axis in call.inputs["structure_residue_axes"].scientific_axes
        }
        joined = []
        for candidate in collection.items:
            reference = references_by_id[candidate.candidate_id]
            residue_axis = axes_by_reference[reference]
            if residue_axis.structure != candidate.data:
                raise ValueError(
                    "SimpleFold confidence resolved axis contradicts its "
                    "structure Candidate"
                )
            joined.append(
                (
                    candidate,
                    reference,
                    residue_axis,
                    admitted_axes_by_reference[reference],
                )
            )
        if any(
            not any(residue_axis.ca_coordinate_mask)
            for _, _, residue_axis, _ in joined
        ):
            raise ValueError(
                "SimpleFold confidence requires at least one resolved CA "
                "coordinate per structure"
            )
        return tuple(joined)

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError(
                "SimpleFold confidence has no Workflow parameters"
            )
        candidates_with_axes = self._structure_candidates_with_axes(call)
        observations: list[ScoreObservation] = []
        for candidate_index, (
            _candidate,
            subject,
            residue_axis,
            axis_reference,
        ) in enumerate(candidates_with_axes):
            adapter_result = self._adapter.evaluate(
                residue_axis=residue_axis,
                engine_role=f"confidence_subject_{candidate_index}",
            )
            values = adapter_result.per_residue_plddt
            finite_values = [value for value in values if value is not None]
            mean_value = math.fsum(finite_values) / len(finite_values)
            for metric_id, value in (
                ("structure.plddt.per_residue", list(values)),
                ("structure.plddt.mean_residue", mean_value),
            ):
                produced = self._produced_observations[metric_id]
                observations.append(
                    ScoreObservation(
                        subject=subject,
                        metric=produced.metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=value,
                        residue_axis=axis_reference,
                        source_partition=produced.output_partition,
                    )
                )
        return {
            "confidence_observations": ScoreCollection(
                "simplefold-existing-structure-confidence",
                observations,
            )
        }
