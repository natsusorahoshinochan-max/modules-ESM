"""Canonical ProteinMPNN Scientific Operation implementations."""

from __future__ import annotations

import hashlib
from typing import Any, cast

from core.operation import (
    OperationResources,
    OperationCall,
)
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.observation import (
    IntrinsicObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ResolvedStructureResidueAxis
from modules.proteinmpnn.domain import ProteinMPNNConstraints
from modules.structure_transform.domain import (
    CandidateResolvedResidueAxisAssociations,
)

from .adapter import LocalProteinMPNNAdapter
from .domain import (
    author_constraints,
    random_fixed_positions,
)


_CANONICAL_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


def _require_sequence_axis(
    sequence: ProteinSequence,
    residue_axis: ResolvedStructureResidueAxis,
    subject: str,
) -> None:
    if not set(sequence.sequence) <= _CANONICAL_AMINO_ACIDS or (
        sequence.residue_ids != residue_axis.layout.residue_ids
    ):
        raise ValueError(f"{subject} sequence must use the exact resolved residue axis")


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
    """Read the ordered resolved-axis value without re-validating it.

    The admitted value already binds every exact structure subject to its axis,
    and its entry order is the owner of every parent slot. The scientific-axis
    projection is the same value's own projection, so its references line up
    with the entries and are used directly.
    """
    axis_input = call.inputs["structure_residue_axes"]
    associations = cast(
        CandidateResolvedResidueAxisAssociations,
        axis_input.value,
    )
    return tuple(
        (entry.subject, entry.residue_axis, axis_reference)
        for entry, axis_reference in zip(
            associations.entries,
            axis_input.scientific_axes,
            strict=True,
        )
    )


class ProteinMPNNConstraintsImplementation:
    """Author one complete identity-addressed constraint value."""

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        with self._resources.engine_invocation():
            constraints = author_constraints(
                call.inputs["structure_residue_axis"].value.layout,
                call.node_parameters,
            )
        return {"constraints": constraints}


class ProteinMPNNRandomFixedPositionsImplementation:
    """Choose a stable identity-addressed fixed-residue subset."""

    def __init__(self, resources: OperationResources) -> None:
        self._resources = resources

    def execute(self, call: OperationCall) -> dict[str, Any]:
        with self._resources.engine_invocation():
            constraints = random_fixed_positions(
                call.inputs["structure_residue_axis"].value.layout,
                effective_seed=call.node_parameters["effective_seed"],
                fraction=call.node_parameters["fraction"],
            )
        return {"constraints": constraints}


class ProteinMPNNDesignImplementation:
    """Create sequence Candidates while preserving exact parent lineage."""

    def __init__(
        self,
        *,
        adapter: LocalProteinMPNNAdapter,
    ) -> None:
        self._adapter = adapter

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

    def execute(self, call: OperationCall) -> dict[str, Any]:
        parents = _resolved_axis_entries(call)
        seed = call.node_parameters["effective_seed"]
        count = call.node_parameters["num_sequences"]
        temperature = call.node_parameters["temperature"]
        noise = call.node_parameters["backbone_noise"]
        reference_input = call.inputs.get("sequence")
        reference = (
            None
            if reference_input is None
            else cast(ProteinSequence, reference_input.value)
        )
        constraint_input = call.inputs.get("constraints")
        constraints = cast(
            ProteinMPNNConstraints | None,
            None if constraint_input is None else constraint_input.value,
        )
        constraint_digest = (
            None
            if constraint_input is None
            else constraint_input.content_digest
        )
        candidates: list[Candidate] = []
        for parent_index, (
            parent_reference,
            residue_axis,
            _axis_reference,
        ) in enumerate(parents):
            if reference is not None:
                _require_sequence_axis(reference, residue_axis, "reference")
            if (
                constraints is not None
                and constraints.layout != residue_axis.layout
            ):
                raise ValueError(
                    "constraints must use the exact resolved residue axis"
                )
            parent_ids = (parent_reference.candidate_id,)
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
        CandidateDataReference,
        CandidateDataReference,
        ResolvedStructureResidueAxis,
        ResidueAxisReference,
    ]:
        parents = _resolved_axis_entries(call)
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
        structure_reference, residue_axis, axis_reference = parents[0]
        sequence = sequences.items[0]
        if sequence.parent_ids != (structure_reference.candidate_id,):
            raise ValueError(
                "ProteinMPNN scoring inputs do not identify one sequence "
                "Candidate and its exact parent structure"
            )
        sequence_reference = admitted_sequences.candidate_data[0]
        return (
            sequence,
            structure_reference,
            sequence_reference,
            residue_axis,
            axis_reference,
        )

    def execute(self, call: OperationCall) -> dict[str, Any]:
        (
            sequence_candidate,
            _structure_reference,
            sequence_reference,
            residue_axis,
            axis_reference,
        ) = self._subject(call)
        sequence = cast(ProteinSequence, sequence_candidate.data)
        _require_sequence_axis(sequence, residue_axis, "scoring")
        score = self._adapter.score(
            residue_axis=residue_axis,
            sequence=sequence,
        )
        observation = ScoreObservation(
            subject=sequence_reference,
            metric=self._metric,
            method=self._method,
            context=IntrinsicObservationContext(),
            source_partition="default",
            value=score,
            residue_axis=axis_reference,
        )
        return {
            "scores": ScoreCollection(
                "proteinmpnn-score-observations",
                [observation],
            )
        }
