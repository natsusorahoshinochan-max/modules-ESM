"""Canonical folding Operations behind provider-independent Adapter DTOs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
from typing import Any

from core.operation import (
    AdmittedPort,
    OperationCall,
    ResolvedProducedObservation,
)
from core.port_types import builtin_frozen_catalog
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ProteinStructure,
    ResidueLayout,
    ResidueAxisReference,
    ResolvedStructureResidueAxis,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.protein import residue_identity_chain, validate_residue_layout
from modules.structure_prediction.domain import (
    ConfidenceFact,
    ConfidenceFactCollection,
    PredictionResidueAxis,
    prediction_key,
)
from modules.structure_prediction.port_types import (
    PREDICTION_RESIDUE_AXIS_PORT_TYPE,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.port_types import RESOLVED_AXIS_PORT_TYPE

from .adapter import (
    ESMFold2Adapter,
)
from .simplefold_adapter import (
    SimpleFoldAdapter,
)
from .simplefold_confidence_adapter import (
    SimpleFoldConfidenceAdapter,
)


_STRUCTURE_PORT_TYPE = builtin_frozen_catalog().require_port_type(
    "protein.structure",
    "4.0.0",
)
_FOLDING_SEQUENCE_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWY")


def _prediction_axis(
    sequence: ProteinSequence,
    source: CandidateDataReference,
) -> PredictionResidueAxis:
    if any(
        symbol not in _FOLDING_SEQUENCE_ALPHABET
        for symbol in sequence.sequence
    ):
        raise ValueError("folding requires a canonical protein sequence")
    residue_ids = (
        tuple(sequence.residue_ids)
        if sequence.residue_ids is not None
        else tuple(
            f"A:{index}"
            for index in range(1, len(sequence.sequence) + 1)
        )
    )
    chain_order: list[str] = []
    for residue_id in residue_ids:
        chain_id = residue_identity_chain(
            residue_id,
            subject="folding prediction residue identity",
        )
        if not chain_order or chain_order[-1] != chain_id:
            chain_order.append(chain_id)
    if len(chain_order) != 1:
        raise ValueError("folding requires a single-chain protein sequence")
    layout = validate_residue_layout(
        ResidueLayout(
            chain_id=",".join(chain_order),
            length=len(sequence.sequence),
            residue_ids=residue_ids,
        ),
        subject="folding prediction residue axis",
    )
    return PredictionResidueAxis(
        source=source,
        layout=layout,
        sequence=ProteinSequence(
            sequence=sequence.sequence,
            residue_ids=residue_ids,
        ),
    )


def _prediction_axes(
    parents: Sequence[Candidate],
    parent_references: Sequence[CandidateDataReference],
) -> tuple[PredictionResidueAxis, ...]:
    axes: list[PredictionResidueAxis] = []
    for parent, parent_reference in zip(
        parents,
        parent_references,
        strict=True,
    ):
        sequence = parent.data
        assert type(sequence) is ProteinSequence
        axes.append(_prediction_axis(sequence, parent_reference))
    return tuple(axes)


def _confidence_fact(
    *,
    output_slot: int,
    structure: ProteinStructure,
    prediction_axis: PredictionResidueAxis,
    per_residue_plddt: Sequence[float | None],
    ptm: float | None,
    pae: Sequence[Sequence[float]] | None,
) -> tuple[str, ConfidenceFact]:
    structure_content_digest = _STRUCTURE_PORT_TYPE.content_digest(
        structure
    )
    prediction_axis_content_digest = (
        PREDICTION_RESIDUE_AXIS_PORT_TYPE.content_digest(prediction_axis)
    )
    key = prediction_key(
        output_role="structure_candidates",
        output_slot=output_slot,
        structure_content_digest=structure_content_digest,
        prediction_axis_content_digest=prediction_axis_content_digest,
    )
    return key, ConfidenceFact(
        prediction_key=key,
        structure_content_digest=structure_content_digest,
        prediction_axis=prediction_axis,
        plddt_per_residue=tuple(per_residue_plddt),
        ptm=ptm,
        pae=(
            None
            if pae is None
            else tuple(tuple(row) for row in pae)
        ),
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
    def _inputs(inputs: Mapping[str, AdmittedPort]) -> list[Candidate]:
        if set(inputs) != {"sequence_candidates"}:
            raise ValueError(
                "folding requires one sequence Candidate Collection"
            )
        collection = inputs["sequence_candidates"].value
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
                "protein-workbench-esmfold2-call/v3\0"
                f"{effective_seed}\0{parent_content_digest}\0"
                f"{parent_index}\0{sample_index}"
            ).encode()
        ).digest()
        return int.from_bytes(digest[:4], "big")

    @staticmethod
    def _parent_references(
        call: OperationCall,
        parents: Sequence[Candidate],
    ) -> tuple[CandidateDataReference, ...]:
        digest_set = call.inputs["sequence_candidates"]
        by_candidate_id = {
            item.candidate_id: item
            for item in digest_set.candidate_data
        }
        return tuple(by_candidate_id[parent.candidate_id] for parent in parents)

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.binding_parameters:
            raise ValueError("ESMFold2 accepts no Binding parameters")
        parents = self._inputs(call.inputs)
        effective_seed, sample_count = self._parameters(call.node_parameters)
        parent_references = self._parent_references(call, parents)
        prediction_axes = _prediction_axes(parents, parent_references)

        candidates: list[Candidate] = []
        confidence_facts: list[ConfidenceFact] = []
        for parent_index, parent in enumerate(parents):
            sequence = parent.data
            assert type(sequence) is ProteinSequence
            axis = prediction_axes[parent_index]
            for sample_index in range(sample_count):
                call_seed = self._call_seed(
                    effective_seed,
                    parent_references[parent_index].content_digest,
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
                key, fact = _confidence_fact(
                    output_slot=len(candidates),
                    structure=adapter_result.structure,
                    prediction_axis=axis,
                    per_residue_plddt=(
                        adapter_result.confidence.per_residue_plddt
                    ),
                    ptm=adapter_result.confidence.ptm,
                    pae=adapter_result.confidence.pae,
                )
                metadata = {
                    "parent_index": parent_index,
                    "sample_index": sample_index,
                    "prediction_key": key,
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
                confidence_facts.append(fact)
        return {
            "structure_candidates": CandidateCollection(
                "folding-structure-candidates",
                "protein.structure",
                candidates,
            ),
            "confidence_facts": ConfidenceFactCollection(
                observation_method=self._method,
                entries=tuple(confidence_facts),
            ),
        }


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
    def _inputs(inputs: Mapping[str, AdmittedPort]) -> list[Candidate]:
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
        parent_references = (
            ESMFold2FoldingImplementation._parent_references(
                call,
                parents,
            )
        )
        prediction_axes = _prediction_axes(parents, parent_references)
        candidates: list[Candidate] = []
        confidence_facts: list[ConfidenceFact] = []
        for parent_index, parent in enumerate(parents):
            sequence = parent.data
            assert type(sequence) is ProteinSequence
            axis = prediction_axes[parent_index]
            call_seed = self._call_seed(
                effective_seed,
                parent_references[parent_index].content_digest,
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
                key, fact = _confidence_fact(
                    output_slot=len(candidates),
                    structure=sample.structure,
                    prediction_axis=axis,
                    per_residue_plddt=sample.per_residue_plddt,
                    ptm=None,
                    pae=None,
                )
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
                            "prediction_key": key,
                        },
                    )
                )
                confidence_facts.append(fact)
        return {
            "structure_candidates": CandidateCollection(
                "simplefold-structure-candidates",
                "protein.structure",
                candidates,
            ),
            "confidence_facts": ConfidenceFactCollection(
                observation_method=self._method,
                entries=tuple(confidence_facts),
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
    def _structure_candidates_with_axes(
        call: OperationCall,
    ) -> tuple[
        tuple[
            Candidate,
            CandidateDataReference,
            ResolvedStructureResidueAxis,
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
        if (
            type(collection) is not CandidateCollection
            or collection.item_type != "protein.structure"
            or not collection.items
            or type(associations)
            is not CandidateResolvedResidueAxisAssociations
        ):
            raise ValueError(
                "SimpleFold confidence requires exact structure Candidates "
                "and resolved axes"
            )

        candidates_by_id: dict[str, Candidate] = {}
        for candidate in collection.items:
            if (
                type(candidate) is not Candidate
                or type(candidate.data) is not ProteinStructure
                or candidate.candidate_id in candidates_by_id
            ):
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

        joined = []
        for candidate in collection.items:
            reference = references_by_id[candidate.candidate_id]
            residue_axis = axes_by_reference[reference]
            if residue_axis.structure != candidate.data:
                raise ValueError(
                    "SimpleFold confidence resolved axis contradicts its "
                    "structure Candidate"
                )
            joined.append((candidate, reference, residue_axis))
        if any(
            not any(residue_axis.ca_coordinate_mask)
            for _, _, residue_axis in joined
        ):
            raise ValueError(
                "SimpleFold confidence requires at least one resolved CA "
                "coordinate per structure"
            )
        return tuple(joined)

    @staticmethod
    def _resolved_axis_reference(
        subject: CandidateDataReference,
        residue_axis: ResolvedStructureResidueAxis,
    ) -> ResidueAxisReference:
        return ResidueAxisReference(
            axis_kind="resolved_structure",
            axis_contract=ExactContractReference(
                contract_kind="port_type",
                contract_id=RESOLVED_AXIS_PORT_TYPE.type_id,
                contract_version=RESOLVED_AXIS_PORT_TYPE.version,
                contract_digest=RESOLVED_AXIS_PORT_TYPE.contract_digest,
            ),
            axis_content_digest=RESOLVED_AXIS_PORT_TYPE.content_digest(
                residue_axis
            ),
            source=subject,
            layout=residue_axis.layout,
        )

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
        ) in enumerate(candidates_with_axes):
            adapter_result = self._adapter.evaluate(
                residue_axis=residue_axis,
                engine_role=f"confidence_subject_{candidate_index}",
            )
            values = adapter_result.per_residue_plddt
            finite_values = [value for value in values if value is not None]
            mean_value = math.fsum(finite_values) / len(finite_values)
            axis_reference = self._resolved_axis_reference(
                subject,
                residue_axis,
            )
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
