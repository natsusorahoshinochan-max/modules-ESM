"""Canonical folding Operations behind provider-independent Adapter DTOs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
from typing import Any

from core.operation import (
    OperationCall,
    ResolvedProducedObservation,
)
from datatypes import (
    Candidate,
    CandidateCollection,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ProteinStructure,
    ScoreCollection,
    ScoreObservation,
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
        produced_observations: Sequence[ResolvedProducedObservation],
    ) -> None:
        self._adapter = adapter
        self._method = method
        self._produced_observations = {
            observation.metric.contract_id: observation
            for observation in produced_observations
        }

    @staticmethod
    def _parameters(parameters: Mapping[str, Any]) -> tuple[int, int]:
        if set(parameters) != {"effective_seed", "num_samples"}:
            raise ValueError("folding parameters are not fully resolved")
        seed = parameters["effective_seed"]
        count = parameters["num_samples"]
        if (
            type(seed) is not int
            or seed < 0
            or seed > 9_007_199_254_740_991
            or type(count) is not int
            or count < 1
            or count > 100
        ):
            raise ValueError("folding parameters are outside their contract")
        return seed, count

    @staticmethod
    def _inputs(inputs: Mapping[str, Any]) -> list[Candidate]:
        if set(inputs) != {"sequence_candidates"}:
            raise ValueError(
                "folding requires one sequence Candidate Collection"
            )
        collection = inputs["sequence_candidates"]
        if (
            type(collection) is not CandidateCollection
            or collection.item_type != "protein.sequence"
            or not collection.items
        ):
            raise ValueError(
                "folding requires non-empty protein sequence Candidates"
            )
        for candidate in collection.items:
            if type(candidate) is not Candidate or type(
                candidate.data
            ) is not ProteinSequence:
                raise ValueError("folding received an incomplete sequence")
        return list(collection.items)

    @staticmethod
    def _call_seed(
        effective_seed: int,
        parent_content_digest: str,
        parent_index: int,
        sample_index: int,
    ) -> int:
        digest = hashlib.sha256(
            (
                "protein-workbench-esmfold2-call/v2\0"
                f"{effective_seed}\0{parent_content_digest}\0"
                f"{parent_index}\0{sample_index}"
            ).encode()
        ).digest()
        return int.from_bytes(digest[:7], "big") % 9_007_199_254_740_992

    @staticmethod
    def _parent_content_digests(
        call: OperationCall,
        parents: Sequence[Candidate],
    ) -> tuple[str, ...]:
        digest_set = call.input_content_digests.get("sequence_candidates")
        if (
            digest_set is None
            or digest_set.port_type_id != "candidate.collection"
        ):
            raise ValueError(
                "folding requires admitted sequence Candidate content "
                "identities"
            )
        by_candidate_id = {
            item.candidate_id: item
            for item in digest_set.candidate_data
        }
        if (
            len(by_candidate_id) != len(digest_set.candidate_data)
            or set(by_candidate_id)
            != {parent.candidate_id for parent in parents}
            or any(
                item.data_type_id != "protein.sequence"
                for item in by_candidate_id.values()
            )
        ):
            raise ValueError(
                "folding sequence Candidate content identities are incomplete"
            )
        return tuple(
            by_candidate_id[parent.candidate_id].content_digest
            for parent in parents
        )

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.binding_parameters:
            raise ValueError("ESMFold2 accepts no Binding parameters")
        parents = self._inputs(call.inputs)
        effective_seed, sample_count = self._parameters(call.node_parameters)
        parent_content_digests = self._parent_content_digests(call, parents)

        candidates: list[Candidate] = []
        confidence: list[ScoreObservation] = []
        pae: list[ScoreObservation] = []
        for parent_index, parent in enumerate(parents):
            sequence = parent.data
            assert type(sequence) is ProteinSequence
            for sample_index in range(sample_count):
                call_seed = self._call_seed(
                    effective_seed,
                    parent_content_digests[parent_index],
                    parent_index,
                    sample_index,
                )
                adapter_result = self._adapter.fold(
                    sequence=sequence,
                    derived_call_seed=call_seed,
                    engine_role=(
                        f"fold_parent_{parent_index}_sample_{sample_index}"
                    ),
                )
                candidate_id = (
                    f"fold-{parent_index}-sample-{sample_index}"
                )
                metadata = {
                    "parent_index": parent_index,
                    "sample_index": sample_index,
                }
                if adapter_result.effective_call_seed is not None:
                    metadata.update(
                        {
                            "configured_base_seed": effective_seed,
                            "effective_call_seed": (
                                adapter_result.effective_call_seed
                            ),
                        }
                    )
                candidate = Candidate(
                    candidate_id,
                    adapter_result.structure,
                    [parent.candidate_id],
                    metadata,
                )
                candidates.append(candidate)
                per_residue_plddt = (
                    adapter_result.confidence.per_residue_plddt
                )
                finite_plddt = [
                    value
                    for value in per_residue_plddt
                    if value is not None
                ]
                values = (
                    ("structure.ptm", adapter_result.confidence.ptm),
                    (
                        "structure.plddt.per_residue",
                        list(per_residue_plddt),
                    ),
                    (
                        "structure.plddt.mean_residue",
                        math.fsum(finite_plddt) / len(finite_plddt),
                    ),
                )
                for metric_id, value in values:
                    produced = self._produced_observations[metric_id]
                    confidence.append(
                        ScoreObservation(
                            candidate_id=candidate_id,
                            metric=produced.metric,
                            method=self._method,
                            context=IntrinsicObservationContext(),
                            value=value,
                            source_partition=produced.output_partition,
                        )
                    )
                produced = self._produced_observations["structure.pae"]
                pae.append(
                    ScoreObservation(
                        candidate_id=candidate_id,
                        metric=produced.metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=[
                            list(row)
                            for row in adapter_result.confidence.pae
                        ],
                        source_partition=produced.output_partition,
                    )
                )
        return {
            "structure_candidates": CandidateCollection(
                "folding-structure-candidates",
                "protein.structure",
                candidates,
            ),
            "confidence_observations": ScoreCollection(
                "folding-confidence",
                confidence,
            ),
            "pae_observations": ScoreCollection(
                "folding-pae",
                pae,
            ),
        }


class SimpleFoldFoldingImplementation:
    """Fold sequence Candidates through the exact local SimpleFold Binding."""

    def __init__(
        self,
        *,
        adapter: SimpleFoldAdapter,
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
    def _parameters(
        node_parameters: Mapping[str, Any],
        binding_parameters: Mapping[str, Any],
    ) -> tuple[int, int, int]:
        if (
            set(node_parameters) != {"effective_seed", "num_samples"}
            or set(binding_parameters) != {"num_steps"}
        ):
            raise ValueError("SimpleFold parameters are not fully resolved")
        seed = node_parameters["effective_seed"]
        sample_count = node_parameters["num_samples"]
        num_steps = binding_parameters["num_steps"]
        if (
            type(seed) is not int
            or not 0 <= seed <= 9_007_199_254_740_991
            or type(sample_count) is not int
            or not 1 <= sample_count <= 100
            or type(num_steps) is not int
            or not 1 <= num_steps <= 50
        ):
            raise ValueError("SimpleFold parameters are outside their contract")
        return seed, sample_count, num_steps

    @staticmethod
    def _inputs(inputs: Mapping[str, Any]) -> list[Candidate]:
        return ESMFold2FoldingImplementation._inputs(inputs)

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
        parents = self._inputs(call.inputs)
        effective_seed, sample_count, num_steps = self._parameters(
            call.node_parameters,
            call.binding_parameters,
        )
        parent_content_digests = (
            ESMFold2FoldingImplementation._parent_content_digests(
                call,
                parents,
            )
        )
        candidates: list[Candidate] = []
        confidence: list[ScoreObservation] = []
        for parent_index, parent in enumerate(parents):
            sequence = parent.data
            assert type(sequence) is ProteinSequence
            call_seed = self._call_seed(
                effective_seed,
                parent_content_digests[parent_index],
                parent_index,
            )
            adapter_result = self._adapter.fold(
                sequence=sequence,
                num_steps=num_steps,
                num_samples=sample_count,
                derived_call_seed=call_seed,
                engine_role=f"fold_parent_{parent_index}",
            )
            for sample_index, sample in enumerate(adapter_result.samples):
                candidate_id = (
                    f"simplefold-parent-{parent_index}-"
                    f"sample-{sample_index}"
                )
                values = sample.per_residue_plddt
                candidates.append(
                    Candidate(
                        candidate_id,
                        sample.structure,
                        [parent.candidate_id],
                        {
                            "parent_index": parent_index,
                            "sample_index": sample_index,
                            "configured_base_seed": effective_seed,
                            "effective_call_seed": (
                                adapter_result.effective_call_seed
                            ),
                            "num_steps": num_steps,
                        },
                    )
                )
                for metric_id, value in (
                    ("structure.plddt.per_residue", list(values)),
                    (
                        "structure.plddt.mean_residue",
                        math.fsum(values) / len(values),
                    ),
                ):
                    produced = self._produced_observations[metric_id]
                    confidence.append(
                        ScoreObservation(
                            candidate_id=candidate_id,
                            metric=produced.metric,
                            method=self._method,
                            context=IntrinsicObservationContext(),
                            value=value,
                            source_partition=produced.output_partition,
                        )
                    )
        return {
            "structure_candidates": CandidateCollection(
                "simplefold-structure-candidates",
                "protein.structure",
                candidates,
            ),
            "confidence_observations": ScoreCollection(
                "simplefold-confidence",
                confidence,
            ),
            "pae_observations": ScoreCollection(
                "simplefold-pae",
                [],
            ),
        }


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
    def _inputs(inputs: Mapping[str, Any]) -> list[Candidate]:
        if set(inputs) != {"structure_candidates"}:
            raise ValueError(
                "SimpleFold confidence requires structure Candidates"
            )
        collection = inputs["structure_candidates"]
        if (
            type(collection) is not CandidateCollection
            or collection.item_type != "protein.structure"
            or not collection.items
        ):
            raise ValueError(
                "SimpleFold confidence requires non-empty structures"
            )
        for candidate in collection.items:
            if (
                type(candidate) is not Candidate
                or type(candidate.data) is not ProteinStructure
            ):
                raise ValueError(
                    "SimpleFold confidence received an incomplete structure"
                )
        return list(collection.items)

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError(
                "SimpleFold confidence has no Workflow parameters"
            )
        candidates = self._inputs(call.inputs)
        observations: list[ScoreObservation] = []
        for candidate_index, candidate in enumerate(candidates):
            structure = candidate.data
            assert type(structure) is ProteinStructure
            adapter_result = self._adapter.evaluate(
                structure=structure,
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
                        candidate_id=candidate.candidate_id,
                        metric=produced.metric,
                        method=self._method,
                        context=IntrinsicObservationContext(),
                        value=value,
                        source_partition=produced.output_partition,
                    )
                )
        return {
            "confidence_observations": ScoreCollection(
                "simplefold-existing-structure-confidence",
                observations,
            )
        }
