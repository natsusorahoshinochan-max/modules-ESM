"""Candidate-associated v4 structure-comparison operations."""

from __future__ import annotations

from typing import Any

from core import OperationCall, OperationContext
from datatypes import (
    CandidateDataReference,
    PairwiseCandidateMapping,
    ScoreCollection,
    ScoreObservation,
)
from modules.structure_transform import (
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)

from .alignment import align_resolved_axes
from .contracts import (
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    STRUCTURE_FIRST_TM_ALIGN_METHOD_REFERENCE,
)
from .domain import StructureAlignmentEvidence
from .metrics import (
    evidence_metric_context,
    rmsd_from_evidence,
    tm_score_from_evidence,
)


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
    value: CandidateResolvedResidueAxisAssociations,
    references: tuple[CandidateDataReference, ...],
    *,
    role: str,
) -> dict[CandidateDataReference, CandidateResolvedResidueAxisAssociation]:
    by_reference = {entry.subject: entry for entry in value.entries}
    if set(by_reference) != set(references):
        raise ValueError(
            f"{role} residue axes must cover exact Candidate references"
        )
    return by_reference


def _fixed_reference_pairs(
    subjects: tuple[CandidateDataReference, ...],
    references: tuple[CandidateDataReference, ...],
) -> tuple[tuple[CandidateDataReference, CandidateDataReference], ...]:
    if len(references) != 1:
        raise ValueError("fixed-reference comparison requires one reference")
    return tuple((subject, references[0]) for subject in subjects)


def _counterpart_pairs(
    value: PairwiseCandidateMapping,
    subjects: tuple[CandidateDataReference, ...],
    references: tuple[CandidateDataReference, ...],
) -> tuple[tuple[CandidateDataReference, CandidateDataReference], ...]:
    if not value.entries:
        raise ValueError("counterpart comparison requires exact Candidate pairing")
    subjects_by_identity = {item: item for item in subjects}
    references_by_identity = {item: item for item in references}
    pairs: list[tuple[CandidateDataReference, CandidateDataReference]] = []
    for entry in value.entries:
        if (
            entry.subject.data_type_id != "protein.structure"
            or entry.reference.data_type_id != "protein.structure"
        ):
            raise ValueError(
                "structure comparison pairing requires structure Candidate "
                "references"
            )
        subject = subjects_by_identity.get(entry.subject)
        reference = references_by_identity.get(entry.reference)
        if subject is None or reference is None:
            raise ValueError("Candidate pairing contradicts exact content")
        pairs.append((subject, reference))
    if (
        len(pairs) != len(subjects)
        or len(pairs) != len(references)
        or {subject for subject, _ in pairs} != set(subjects)
        or {reference for _, reference in pairs} != set(references)
    ):
        raise ValueError("Candidate pairing must be complete and one-to-one")
    return tuple(pairs)


class StructureComparisonImplementation:
    """Execute only exact Candidate-associated v4 comparison contracts."""

    def __init__(
        self,
        context: OperationContext,
        operation: str,
        pairing_mode: str | None = None,
    ) -> None:
        self._run_resources = context.resources
        self._method = context.method
        self._produced_observations = context.produced_observations
        self._operation = operation
        self._pairing_mode = pairing_mode

    def execute(self, call: OperationCall) -> dict[str, Any]:
        if self._operation in {"align_single", "align_pairwise"}:
            return self._align(call)
        if self._operation in {"rmsd", "tm_score"}:
            return self._observe(call)
        raise ValueError("unknown structure comparison operation")

    def _alignment_method(self) -> str:
        if self._method == SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE:
            return "sequence_primary_affine"
        if self._method == STRUCTURE_FIRST_TM_ALIGN_METHOD_REFERENCE:
            return "structure_first_tm_align"
        raise ValueError("Binding selected an unknown alignment Method")

    def _align(self, call: OperationCall) -> dict[str, Any]:
        pin_matching_chain_ids = call.node_parameters.get(
            "pin_matching_chain_ids",
            False,
        )

        subjects = _candidate_references(call, port_name="subjects")
        references = _candidate_references(call, port_name="references")
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
        if self._operation == "align_single":
            if len(subjects) != 1 or len(references) != 1:
                raise ValueError(
                    "single alignment requires one subject and one reference"
                )
            pairs = ((subjects[0], references[0]),)
        elif self._pairing_mode == "fixed_reference":
            pairs = _fixed_reference_pairs(subjects, references)
        elif self._pairing_mode == "per_subject_counterpart":
            pairs = _counterpart_pairs(
                call.inputs["pairing"].value,
                subjects,
                references,
            )
        else:
            raise ValueError("pairwise alignment Binding lacks pairing semantics")

        method = self._alignment_method()
        alignments: list[StructureAlignmentEvidence] = []
        for subject, reference in pairs:
            subject_association = subject_axes[subject]
            reference_association = reference_axes[reference]
            with self._run_resources.engine_invocation(
                engine_role=method,
            ):
                resolved = align_resolved_axes(
                    subject_association.residue_axis,
                    reference_association.residue_axis,
                    correspondence_method=method,
                    pin_matching_chain_ids=pin_matching_chain_ids,
                )
            alignments.append(
                StructureAlignmentEvidence(
                    subject=subject_association.subject,
                    reference=reference_association.subject,
                    subject_axis_content_digest=(
                        admitted_subject_axes[
                            subject_association.subject
                        ].axis_content_digest
                    ),
                    reference_axis_content_digest=(
                        admitted_reference_axes[
                            reference_association.subject
                        ].axis_content_digest
                    ),
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
        subjects = [alignment.subject for alignment in alignments]
        references = [alignment.reference for alignment in alignments]
        if len(set(subjects)) != len(subjects):
            raise ValueError("alignment evidence repeats a subject")
        subject_scope = _candidate_references(call, port_name="subjects")
        reference_scope = _candidate_references(call, port_name="references")
        if self._pairing_mode == "fixed_reference":
            expected_pairs = _fixed_reference_pairs(
                subject_scope,
                reference_scope,
            )
        else:
            expected_pairs = _counterpart_pairs(
                call.inputs["pairing"].value,
                subject_scope,
                reference_scope,
            )
        evidence_pairs = {
            (alignment.subject, alignment.reference)
            for alignment in alignments
        }
        scoped_pairs = set(expected_pairs)
        if evidence_pairs != scoped_pairs:
            raise ValueError(
                "alignment evidence contradicts exact Candidate scope"
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
                            pairing_mode=self._pairing_mode,
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
                    f"{self._pairing_mode}"
                ),
                entries=tuple(entries),
            )
        }
