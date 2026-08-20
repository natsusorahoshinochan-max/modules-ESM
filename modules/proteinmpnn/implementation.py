"""Canonical ProteinMPNN Scientific Operation implementations."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any, cast

from core import AdmittedPort, OperationCall, RunResources
from datatypes import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
    ExactContractReference,
    IntrinsicObservationContext,
    ProteinSequence,
    ResidueAxisReference,
    ResolvedStructureResidueAxis,
    ScoreCollection,
    ScoreObservation,
)
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociations,
)

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
        ResidueAxisReference,
    ],
    ...,
]:
    admitted = call.inputs.get("structure_candidates")
    axis_input = call.inputs.get("structure_residue_axes")
    if (
        admitted is None
        or axis_input is None
    ):
        raise ValueError(
            "ProteinMPNN requires exact structure Candidates and resolved axes"
        )
    collection = cast(CandidateCollection, admitted.value)
    associations = cast(
        CandidateResolvedResidueAxisAssociations,
        axis_input.value,
    )
    if collection.item_type != "protein.structure" or not collection.items:
        raise ValueError(
            "ProteinMPNN requires exact structure Candidates and resolved axes"
        )

    candidates_by_id: dict[str, Candidate] = {}
    for candidate in collection.items:
        if candidate.candidate_id in candidates_by_id:
            raise ValueError(
                "ProteinMPNN structure Candidates are incomplete or duplicate"
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
    admitted_axes_by_reference = {
        axis.source: axis for axis in axis_input.scientific_axes
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
        result.append(
            (
                candidate,
                reference,
                residue_axis,
                admitted_axes_by_reference[reference],
            )
        )
    return tuple(result)


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
                call.inputs["layout"].value,
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
                call.inputs["layout"].value,
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
    def _validate_inputs(inputs: Mapping[str, AdmittedPort]) -> None:
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
        admitted = call.inputs.get("constraints")
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
        reference_input = call.inputs.get("sequence")
        reference = (
            None
            if reference_input is None
            else cast(ProteinSequence, reference_input.value)
        )
        constraint_input = call.inputs.get("constraints")
        constraints = (
            None if constraint_input is None else constraint_input.value
        )
        constraint_digest = self._constraint_digest(call)
        candidates: list[Candidate] = []
        try:
            for parent_index, (
                parent_candidate,
                parent_reference,
                residue_axis,
                _axis_reference,
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
        for parent_candidate, _, _, _ in parents:
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
        ResidueAxisReference,
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
        admitted_sequences = call.inputs["sequence_candidates"]
        sequences = cast(CandidateCollection, admitted_sequences.value)
        if (
            len(parents) != 1
            or sequences.item_type != "protein.sequence"
            or len(sequences.items) != 1
        ):
            raise ValueError(
                "ProteinMPNN scoring requires one structure Candidate and "
                "one sequence Candidate"
            )
        structure, structure_reference, residue_axis, axis_reference = parents[0]
        sequence = sequences.items[0]
        if (
            not structure.candidate_id
            or not sequence.candidate_id
            or sequence.parent_ids != (structure.candidate_id,)
        ):
            raise ValueError(
                "ProteinMPNN scoring inputs do not identify one sequence "
                "Candidate and its exact parent structure"
            )
        sequence_reference = admitted_sequences.candidate_data[0]
        return (
            structure,
            sequence,
            structure_reference,
            sequence_reference,
            residue_axis,
            axis_reference,
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
            axis_reference,
        ) = self._subject(call)
        sequence = cast(ProteinSequence, sequence_candidate.data)
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
            residue_axis=axis_reference,
        )
        return {
            "scores": ScoreCollection(
                "proteinmpnn-score-observations",
                [observation],
            )
        }
