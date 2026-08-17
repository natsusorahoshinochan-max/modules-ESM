"""Canonical ProteinMPNN Scientific Operation implementations."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from core import OperationCall, RunResources
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinMPNNConstraints,
    ProteinSequence,
    ProteinStructure,
    ResidueAxisReference,
    ResolvedStructureResidueAxis,
    ScoreCollection,
    ScoreObservation,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociations,
)
from modules.structure_transform.port_types import RESOLVED_AXIS_PORT_TYPE

from .adapter import LocalProteinMPNNAdapter
from .domain import (
    author_constraints,
    normalize_design_parameters,
    random_fixed_positions,
)


def _reference_key(
    reference: CandidateDataReference,
) -> tuple[str, str, str]:
    return (
        reference.candidate_id,
        reference.data_type_id,
        reference.content_digest,
    )


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
    collection = call.inputs.get("structure_candidates")
    associations = call.inputs.get("structure_residue_axes")
    admitted = call.input_content_digests.get("structure_candidates")
    if (
        type(collection) is not CandidateCollection
        or collection.item_type != "protein.structure"
        or not collection.items
        or type(associations)
        is not CandidateResolvedResidueAxisAssociations
        or admitted is None
        or admitted.port_type_id != "candidate.collection"
    ):
        raise ValueError(
            "ProteinMPNN requires exact structure Candidates and resolved axes"
        )

    candidates_by_id: dict[str, Candidate] = {}
    for candidate in collection.items:
        if (
            type(candidate) is not Candidate
            or type(candidate.data) is not ProteinStructure
            or candidate.candidate_id in candidates_by_id
        ):
            raise ValueError(
                "ProteinMPNN structure Candidates are incomplete or duplicate"
            )
        candidates_by_id[candidate.candidate_id] = candidate

    references_by_id: dict[str, CandidateDataReference] = {}
    for reference in admitted.candidate_data:
        if (
            type(reference) is not CandidateDataReference
            or reference.data_type_id != "protein.structure"
            or reference.candidate_id in references_by_id
        ):
            raise ValueError(
                "ProteinMPNN lacks complete exact structure references"
            )
        references_by_id[reference.candidate_id] = reference
    if set(references_by_id) != set(candidates_by_id):
        raise ValueError(
            "ProteinMPNN lacks complete exact structure references"
        )

    axes_by_reference = {
        entry.subject: entry.residue_axis
        for entry in associations.entries
    }
    references = tuple(
        sorted(references_by_id.values(), key=_reference_key)
    )
    if set(axes_by_reference) != set(references):
        raise ValueError(
            "ProteinMPNN resolved axes must cover exact structure references"
        )

    result = []
    for candidate in collection.items:
        reference = references_by_id[candidate.candidate_id]
        residue_axis = axes_by_reference[reference]
        if residue_axis.structure != candidate.data:
            raise ValueError(
                "ProteinMPNN resolved axis contradicts its structure Candidate"
            )
        result.append((candidate, reference, residue_axis))
    return tuple(result)


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


class ProteinMPNNConstraintsImplementation:
    """Author one complete identity-addressed constraint value."""

    def __init__(self, resources: RunResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if set(call.inputs) != {"layout"} or call.binding_parameters:
            raise ValueError(
                "constraint authoring requires one explicit residue layout"
            )
        with self._resources.engine_invocation():
            constraints = author_constraints(
                call.inputs["layout"],
                call.node_parameters,
            )
        return {"constraints": constraints}


class ProteinMPNNRandomFixedPositionsImplementation:
    """Choose a stable identity-addressed fixed-residue subset."""

    def __init__(self, resources: RunResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if (
            set(call.inputs) != {"layout"}
            or set(call.node_parameters) != {"effective_seed", "fraction"}
            or call.binding_parameters
        ):
            raise ValueError(
                "random fixed-position selection requires resolved parameters"
            )
        with self._resources.engine_invocation():
            constraints = random_fixed_positions(
                call.inputs["layout"],
                effective_seed=call.node_parameters["effective_seed"],
                fraction=call.node_parameters["fraction"],
            )
        return {"constraints": constraints}


class ProteinMPNNDesignImplementation:
    """Create sequence Candidates while preserving exact parent lineage."""

    def __init__(
        self,
        *,
        resources: RunResources,
        adapter: LocalProteinMPNNAdapter,
    ) -> None:
        self._resources = resources
        self._adapter = adapter

    @staticmethod
    def _validate_inputs(inputs: Mapping[str, Any]) -> None:
        allowed = {
            "structure_candidates",
            "structure_residue_axes",
            "sequence",
            "constraints",
        }
        if (
            not set(inputs) <= allowed
            or not {
                "structure_candidates",
                "structure_residue_axes",
            } <= set(inputs)
        ):
            raise ValueError("ProteinMPNN design received undeclared inputs")

    @staticmethod
    def _parameters(
        call: OperationCall,
    ) -> tuple[int, int, float, float]:
        normalized = normalize_design_parameters(
            call.node_parameters,
            call.binding_parameters,
        )
        return (
            int(normalized["effective_seed"]),
            int(normalized["num_sequences"]),
            float(normalized["temperature"]),
            float(normalized["backbone_noise"]),
        )

    @staticmethod
    def _call_seed(
        effective_seed: int,
        parent_content_digest: str,
        parent_slot: int,
    ) -> int:
        digest = hashlib.sha256(
            (
                "protein-workbench-proteinmpnn-parent-seed/v2\0"
                f"{effective_seed}\0"
                f"{parent_slot}\0"
                f"{parent_content_digest}"
            ).encode()
        ).digest()
        return int.from_bytes(digest[:7], "big") % 9_007_199_254_740_992

    @staticmethod
    def _constraint_digest(call: OperationCall) -> str | None:
        admitted = call.input_content_digests.get("constraints")
        if admitted is None:
            return None
        if len(admitted.value_content_digests) != 1:
            raise RuntimeError(
                "ProteinMPNN constraints input content identity is incomplete"
            )
        return admitted.value_content_digests[0]

    def execute(self, call: OperationCall) -> dict[str, Any]:
        self._validate_inputs(call.inputs)
        parents = _structure_candidates_with_axes(call)
        seed, count, temperature, noise = self._parameters(call)
        reference = call.inputs.get("sequence")
        if reference is not None and type(reference) is not ProteinSequence:
            raise ValueError("sequence input must be a complete ProteinSequence")
        constraints = call.inputs.get("constraints")
        if (
            constraints is not None
            and type(constraints) is not ProteinMPNNConstraints
        ):
            raise ValueError(
                "constraints input must be complete ProteinMPNN constraints"
            )
        constraint_digest = self._constraint_digest(call)
        candidates: list[Candidate] = []
        try:
            for parent_index, (
                parent_candidate,
                parent_reference,
                residue_axis,
            ) in enumerate(parents):
                parent_ids = (parent_candidate.candidate_id,)
                call_seed = self._call_seed(
                    seed,
                    parent_reference.content_digest,
                    parent_index,
                )
                sequences = self._adapter.design(
                    residue_axis=residue_axis,
                    num_sequences=count,
                    temperature=temperature,
                    backbone_noise=noise,
                    seed=call_seed,
                    constraints=constraints,
                    reference_sequence=reference,
                    engine_role=f"design_parent_{parent_index}",
                )
                if len(sequences) != count:
                    raise RuntimeError(
                        "ProteinMPNN design returned an incomplete child set"
                    )
                for sample_index, sequence in enumerate(sequences):
                    candidates.append(
                        Candidate(
                            (
                                f"proteinmpnn-parent-{parent_index}-"
                                f"sample-{sample_index}"
                            ),
                            sequence,
                            parent_ids,
                            {
                                "parent_index": parent_index,
                                "sample_index": sample_index,
                                "effective_seed": seed,
                                "effective_call_seed": call_seed,
                                "num_sequences": count,
                                "temperature": temperature,
                                "backbone_noise": noise,
                                "constraint_digest": constraint_digest,
                            },
                        )
                    )
        finally:
            self._adapter.close()
        if len(candidates) != len(parents) * count:
            raise RuntimeError("ProteinMPNN design children are incomplete")
        for parent_candidate, _, _ in parents:
            parent_ids = (parent_candidate.candidate_id,)
            children = [
                candidate
                for candidate in candidates
                if candidate.parent_ids == parent_ids
            ]
            if len(children) != count:
                raise RuntimeError(
                    "ProteinMPNN design parent relationship is incomplete"
                )
        return {
            "sequence_candidates": CandidateCollection(
                "proteinmpnn-sequence-candidates",
                "protein.sequence",
                candidates,
            )
        }


class ProteinMPNNScoreImplementation:
    """Observe one exact sequence Candidate on its exact parent structure."""

    def __init__(
        self,
        *,
        adapter: LocalProteinMPNNAdapter,
        method: ExactContractReference,
        metric: ExactContractReference,
    ) -> None:
        self._adapter = adapter
        self._method = method
        self._metric = metric

    @staticmethod
    def _subject(
        call: OperationCall,
    ) -> tuple[
        Candidate,
        Candidate,
        CandidateDataReference,
        CandidateDataReference,
        ResolvedStructureResidueAxis,
    ]:
        if set(call.inputs) != {
            "structure_candidates",
            "sequence_candidates",
            "structure_residue_axes",
        }:
            raise ValueError(
                "ProteinMPNN scoring requires exact structure and sequence "
                "Candidate inputs with resolved axes"
            )
        parents = _structure_candidates_with_axes(call)
        sequences = call.inputs["sequence_candidates"]
        if (
            len(parents) != 1
            or type(sequences) is not CandidateCollection
            or sequences.item_type != "protein.sequence"
            or len(sequences.items) != 1
        ):
            raise ValueError(
                "ProteinMPNN scoring requires one structure Candidate and "
                "one sequence Candidate"
            )
        structure, structure_reference, residue_axis = parents[0]
        sequence = sequences.items[0]
        admitted_sequences = call.input_content_digests.get(
            "sequence_candidates"
        )
        if (
            type(structure) is not Candidate
            or not structure.candidate_id
            or type(structure.data) is not ProteinStructure
            or type(sequence) is not Candidate
            or not sequence.candidate_id
            or type(sequence.data) is not ProteinSequence
            or sequence.parent_ids != (structure.candidate_id,)
            or admitted_sequences is None
            or admitted_sequences.port_type_id != "candidate.collection"
            or len(admitted_sequences.candidate_data) != 1
        ):
            raise ValueError(
                "ProteinMPNN scoring inputs do not identify one sequence "
                "Candidate and its exact parent structure"
            )
        sequence_reference = admitted_sequences.candidate_data[0]
        if (
            type(sequence_reference) is not CandidateDataReference
            or sequence_reference.data_type_id != "protein.sequence"
            or sequence_reference.candidate_id != sequence.candidate_id
        ):
            raise ValueError(
                "ProteinMPNN scoring lacks the exact sequence reference"
            )
        return (
            structure,
            sequence,
            structure_reference,
            sequence_reference,
            residue_axis,
        )

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if call.node_parameters or call.binding_parameters:
            raise ValueError(
                "ProteinMPNN scoring accepts no Workflow parameters"
            )
        (
            structure_candidate,
            sequence_candidate,
            structure_reference,
            sequence_reference,
            residue_axis,
        ) = self._subject(call)
        sequence = sequence_candidate.data
        assert type(sequence) is ProteinSequence
        try:
            score = self._adapter.score(
                residue_axis=residue_axis,
                sequence=sequence,
            )
        finally:
            self._adapter.close()
        observation = ScoreObservation(
            subject=sequence_reference,
            metric=self._metric,
            method=self._method,
            context=IntrinsicObservationContext(),
            value=score,
            residue_axis=_resolved_axis_reference(
                structure_reference,
                residue_axis,
            ),
        )
        return {
            "scores": ScoreCollection(
                "proteinmpnn-score-observations",
                [observation],
            )
        }
