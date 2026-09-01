"""Candidate-associated structure-comparison operations."""

from __future__ import annotations

from typing import Any, Protocol, cast

from core.operation import OperationCall, OperationContext
from datatypes.candidate import CandidateDataReference
from datatypes.observation import (
    CandidateRelation,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.structure import ResolvedStructureResidueAxis

from .alignment import align_resolved_axes
from .contracts import SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE
from .domain import StructureAlignmentEvidence
from .metrics import (
    evidence_metric_context,
    rmsd_from_evidence,
    tm_score_from_evidence,
)


class _ResolvedAxisAssociation(Protocol):
    subject: CandidateDataReference
    residue_axis: ResolvedStructureResidueAxis


class _ResolvedAxisAssociations(Protocol):
    entries: tuple[_ResolvedAxisAssociation, ...]


def _reference_key(
    reference: CandidateDataReference,
) -> tuple[str, str, str]:
    return (
        reference.candidate_id,
        reference.data_type_id,
        reference.content_digest,
    )


def _candidate_references(
    call: OperationCall,
    *,
    port_name: str,
) -> tuple[CandidateDataReference, ...]:
    admitted = call.inputs[port_name]
    collection = admitted.value
    if collection.item_type != "protein.structure" or not collection.items:
        raise ValueError(
            f"{port_name} must carry non-empty exact structure Candidates"
        )
    return tuple(sorted(admitted.candidate_data, key=_reference_key))


def _axis_associations(
    value: object,
    references: tuple[CandidateDataReference, ...],
    *,
    role: str,
) -> dict[CandidateDataReference, _ResolvedAxisAssociation]:
    associations = cast(_ResolvedAxisAssociations, value)
    by_reference = {entry.subject: entry for entry in associations.entries}
    if set(by_reference) != set(references):
        raise ValueError(
            f"{role} residue axes must cover exact Candidate references"
        )
    return by_reference


def _relation_pairs(
    value: CandidateRelation,
    subjects: tuple[CandidateDataReference, ...],
    references: tuple[CandidateDataReference, ...],
) -> tuple[tuple[CandidateDataReference, CandidateDataReference], ...]:
    if not value.entries:
        raise ValueError("structure comparison requires a non-empty relation")
    subject_scope = set(subjects)
    reference_scope = set(references)
    pairs: list[tuple[CandidateDataReference, CandidateDataReference]] = []
    for entry in value.entries:
        if (
            entry.subject.data_type_id != "protein.structure"
            or entry.reference.data_type_id != "protein.structure"
        ):
            raise ValueError(
                "structure comparison relation requires structure Candidate "
                "references"
            )
        if entry.subject not in subject_scope or entry.reference not in reference_scope:
            raise ValueError("Candidate relation contradicts exact content")
        pairs.append((entry.subject, entry.reference))
    if (
        {subject for subject, _reference in pairs} != subject_scope
        or {reference for _subject, reference in pairs} != reference_scope
    ):
        raise ValueError(
            "Candidate relation must cover every subject and reference"
        )
    return tuple(pairs)


class StructureComparisonImplementation:
    """Execute relation-driven structure alignment and metric projection."""

    def __init__(
        self,
        context: OperationContext,
        operation: str,
    ) -> None:
        self._run_resources = context.resources
        self._method = context.method
        self._produced_observations = context.produced_observations
        self._operation = operation

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if self._operation == "align_pairs":
            return self._align(call)
        return self._observe(call)

    def _alignment_method(self) -> str:
        if self._method == SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE:
            return "sequence_primary_affine"
        return "structure_first_tm_align"

    def _align(self, call: OperationCall) -> dict[str, Any]:
        subjects = _candidate_references(call, port_name="subjects")
        references = _candidate_references(call, port_name="references")
        pairs = _relation_pairs(
            call.inputs["relation"].value,
            subjects,
            references,
        )
        subject_axes = _axis_associations(
            call.inputs["subject_residue_axes"].value,
            subjects,
            role="subject",
        )
        reference_axes = _axis_associations(
            call.inputs["reference_residue_axes"].value,
            references,
            role="reference",
        )
        admitted_subject_axes = {
            axis.source: axis
            for axis in call.inputs["subject_residue_axes"].scientific_axes
        }
        admitted_reference_axes = {
            axis.source: axis
            for axis in call.inputs["reference_residue_axes"].scientific_axes
        }
        method = self._alignment_method()
        alignments: list[StructureAlignmentEvidence] = []
        for subject, reference in pairs:
            subject_association = subject_axes[subject]
            reference_association = reference_axes[reference]
            with self._run_resources.engine_invocation(engine_role=method):
                resolved = align_resolved_axes(
                    subject_association.residue_axis,
                    reference_association.residue_axis,
                    correspondence_method=method,
                    pin_matching_chain_ids=call.node_parameters[
                        "pin_matching_chain_ids"
                    ],
                )
            alignments.append(
                StructureAlignmentEvidence(
                    subject=subject_association.subject,
                    reference=reference_association.subject,
                    subject_axis_content_digest=admitted_subject_axes[
                        subject_association.subject
                    ].axis_content_digest,
                    reference_axis_content_digest=admitted_reference_axes[
                        reference_association.subject
                    ].axis_content_digest,
                    segment_map=resolved.segment_map,
                    policy=resolved.policy,
                    correspondence=resolved.correspondence,
                    transform=resolved.transform,
                    normalization=resolved.normalization,
                    rmsd=resolved.rmsd,
                    coverage=resolved.coverage,
                    method=self._method,
                )
            )
        return {"alignments": tuple(alignments)}

    def _observe(self, call: OperationCall) -> dict[str, Any]:
        admitted_alignments = call.inputs["alignments"]
        alignments = admitted_alignments.value
        if not alignments:
            raise ValueError("structure metrics require alignment evidence")
        expected_pairs = _relation_pairs(
            call.inputs["relation"].value,
            _candidate_references(call, port_name="subjects"),
            _candidate_references(call, port_name="references"),
        )
        evidence_pairs = tuple(
            (alignment.subject, alignment.reference)
            for alignment in alignments
        )
        if evidence_pairs != expected_pairs:
            raise ValueError(
                "alignment evidence contradicts the ordered Candidate relation"
            )

        produced = self._produced_observations[0]
        entries: list[ScoreObservation] = []
        with self._run_resources.engine_invocation(
            engine_role=f"evidence_{self._operation}",
        ):
            for alignment, evidence_content_digest in zip(
                alignments,
                admitted_alignments.value_content_digests,
                strict=True,
            ):
                value = (
                    rmsd_from_evidence(alignment)
                    if self._operation == "rmsd"
                    else tm_score_from_evidence(alignment)
                )
                entries.append(
                    ScoreObservation(
                        subject=alignment.subject,
                        metric=produced.metric,
                        method=self._method,
                        context=evidence_metric_context(
                            alignment,
                            evidence_content_digest=evidence_content_digest,
                            pairing_mode="explicit_relation",
                            metric_kind=self._operation,
                        ),
                        value=value,
                        source_partition=produced.output_partition,
                    )
                )
        return {
            "scores": ScoreCollection(
                collection_id=(
                    f"structure-comparison-{self._operation}-"
                    "explicit-relation"
                ),
                entries=tuple(entries),
            )
        }
