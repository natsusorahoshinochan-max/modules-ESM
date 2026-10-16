"""Canonical folding Operations behind provider-independent Adapter DTOs."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import math
from typing import Any

from core.operation import OperationCall, OperationFailedWithOutputs
from .esmfold2_remote import ESMFold2ProviderError
from core.catalog.observation import ProducedObservation
from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.observation import (
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.structure import ResolvedStructureResidueAxis
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociations,
)
from ._output_construction import (
    CompletedFoldingSample,
    FoldingOutputConstruction,
)
from .domain import (
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
        effective_seed = call.effective_randomness.get("effective_seed")
        sample_count = call.node_parameters["num_samples"]
        construction = FoldingOutputConstruction(
            parent_record=call.inputs["sequence_candidates"],
            observation_method=self._method,
        )

        completed_samples: list[CompletedFoldingSample] = []
        for parent in construction.parents:
            for sample_index in range(sample_count):
                call_seed = (
                    None
                    if effective_seed is None
                    else self._call_seed(
                        effective_seed,
                        parent.reference.content_digest,
                        parent.slot,
                        sample_index,
                    )
                )
                try:
                    adapter_result = self._adapter.fold(
                        sequence=parent.sequence,
                        parameters=call.binding_parameters,
                        derived_call_seed=call_seed,
                        engine_role=(
                            f"fold_parent_{parent.slot}_sample_{sample_index}"
                        ),
                    )
                except ESMFold2ProviderError as error:
                    if not completed_samples:
                        raise
                    raise OperationFailedWithOutputs(
                        error, construction.construct(tuple(completed_samples))
                    ) from error
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
        return construction.construct(tuple(completed_samples))


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
        effective_seed = call.effective_randomness["effective_seed"]
        sample_count = call.node_parameters["num_samples"]
        num_steps = call.binding_parameters["num_steps"]
        construction = FoldingOutputConstruction(
            parent_record=call.inputs["sequence_candidates"],
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
                tau=call.binding_parameters["tau"],
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
        return construction.construct(tuple(completed_samples))


class SimpleFoldConfidenceImplementation:
    """Evaluate supplied structures through the fixed confidence-only Method."""

    def __init__(
        self,
        *,
        adapter: SimpleFoldConfidenceAdapter,
        method: ExactContractReference,
        produced_observations: Sequence[ProducedObservation],
    ) -> None:
        self._adapter = adapter
        self._method = method
        self._produced_observations = {
            observation.metric.contract_id: observation
            for observation in produced_observations
        }

    @staticmethod
    def _resolved_axis_entries(
        call: OperationCall,
    ) -> tuple[
        tuple[
            CandidateDataReference,
            ResolvedStructureResidueAxis,
            ResidueAxisReference,
        ],
        ...,
    ]:
        """Read the ordered resolved-axis value and precheck the whole population.

        The admitted value already binds every exact structure subject to its
        axis. This helper joins nothing: it only reads the value's own
        scientific-axis projection and then applies the one Method condition
        that must hold for the complete population before the first Provider
        call.
        """
        axis_input = call.inputs["structure_residue_axes"]
        associations: CandidateResolvedResidueAxisAssociations = (
            axis_input.value
        )
        joined = tuple(
            (entry.subject, entry.residue_axis, axis_reference)
            for entry, axis_reference in zip(
                associations.entries,
                axis_input.scientific_axes,
                strict=True,
            )
        )
        if any(
            not any(residue_axis.ca_coordinate_mask)
            for _, residue_axis, _ in joined
        ):
            raise ValueError(
                "SimpleFold confidence requires at least one resolved CA "
                "coordinate per structure"
            )
        return joined

    def execute(self, call: OperationCall) -> dict[str, Any]:
        candidates_with_axes = self._resolved_axis_entries(call)
        observations: list[ScoreObservation] = []
        for candidate_index, (
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
