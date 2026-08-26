"""Exact input/ESMFold2/SimpleFold consistency classification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from core.operation import (
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
    PairwiseCandidateMapping,
    PairwiseObservationContext,
    ScoreCollection,
    ScoreObservation,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ResolvedStructureResidueAxis
from .contracts import (
    RMSD_FROM_EVIDENCE_METHOD_REFERENCE,
    TM_SCORE_FROM_EVIDENCE_METHOD_REFERENCE,
)
from .domain import (
    StructureAlignmentEvidence,
    ThreeWayComparisonEdge,
    ThreeWayConfidenceEvidence,
    ThreeWayConsistencyEvidence,
    classify_three_way_consistency,
    comparison_is_close,
    confidence_is_eligible,
)


class _ResolvedAxisAssociation(Protocol):
    """Structural view of one admitted resolved-axis association."""

    subject: CandidateDataReference
    residue_axis: ResolvedStructureResidueAxis


class _ResolvedAxisAssociations(Protocol):
    """Structural view of the resolved-axis capability collection."""

    entries: tuple[_ResolvedAxisAssociation, ...]


_MEAN_PLDDT = "structure.plddt.mean_residue"
_TM_SCORE = "structure_comparison.tm_score"
_RMSD = "structure_comparison.rmsd"


def _candidate_scope(
    call: OperationCall,
    port: str,
) -> tuple[Candidate, CandidateDataReference]:
    collection = cast(CandidateCollection, call.inputs[port].value)
    if len(collection.items) != 1:
        raise ValueError(f"{port} must contain exactly one Candidate")
    candidate = collection.items[0]
    return candidate, call.inputs[port].candidate_data[0]


def _value_digest(call: OperationCall, port: str) -> str:
    return call.inputs[port].content_digest


def _axis(
    call: OperationCall,
    port: str,
    subject: CandidateDataReference,
) -> tuple[ResolvedStructureResidueAxis, ResidueAxisReference]:
    associations = cast(
        _ResolvedAxisAssociations,
        call.inputs[port].value,
    )
    matches = tuple(
        item for item in associations.entries if item.subject == subject
    )
    if len(matches) != 1 or len(associations.entries) != 1:
        raise ValueError(f"{port} must bind one exact residue axis")
    admitted_axis = next(
        axis
        for axis in call.inputs[port].scientific_axes
        if axis.source == subject
    )
    return matches[0].residue_axis, admitted_axis


def _observation(
    call: OperationCall,
    port: str,
    *,
    metric: str,
    subject: CandidateDataReference,
) -> ScoreObservation:
    collection = cast(ScoreCollection, call.inputs[port].value)
    matches = tuple(
        item
        for item in collection.entries
        if item.subject == subject
        and item.metric.contract_id == metric
    )
    if len(matches) != 1:
        raise ValueError(f"{port} must contain one exact required Observation")
    return matches[0]


def _confidence(
    call: OperationCall,
    *,
    role: str,
    port: str,
    subject: CandidateDataReference,
    sequence_parent: CandidateDataReference,
    residue_count: int,
) -> ThreeWayConfidenceEvidence:
    observation = _observation(
        call,
        port,
        metric=_MEAN_PLDDT,
        subject=subject,
    )
    axis = observation.residue_axis
    if (
        axis is None
        or axis.source != sequence_parent
        or axis.layout.length != residue_count
    ):
        raise ValueError(f"{port} does not retain the exact sequence parent")
    value = float(observation.value)
    return ThreeWayConfidenceEvidence(
        role=role,
        subject=subject,
        method=observation.method,
        mean_residue_plddt=value,
        eligible=confidence_is_eligible(value),
        score_content_digest=_value_digest(call, port),
    )


def _edge(
    call: OperationCall,
    *,
    edge_id: str,
    alignment_port: str,
    tm_score_port: str,
    rmsd_port: str,
    subject: CandidateDataReference,
    reference: CandidateDataReference,
) -> ThreeWayComparisonEdge:
    alignments = cast(
        tuple[StructureAlignmentEvidence, ...],
        call.inputs[alignment_port].value,
    )
    if len(alignments) != 1:
        raise ValueError(f"{alignment_port} must contain one exact alignment")
    alignment = alignments[0]
    if (alignment.subject, alignment.reference) != (subject, reference):
        raise ValueError(f"{alignment_port} contradicts the declared edge")
    alignment_digest = _value_digest(call, alignment_port)
    tm_score = _observation(
        call,
        tm_score_port,
        metric=_TM_SCORE,
        subject=subject,
    )
    rmsd = _observation(
        call,
        rmsd_port,
        metric=_RMSD,
        subject=subject,
    )
    for observation in (tm_score, rmsd):
        context = observation.context
        if (
            type(context) is not PairwiseObservationContext
            or context.subject.candidate != subject
            or context.reference.candidate != reference
            or context.evidence_content_digest != alignment_digest
            or context.evidence_method != alignment.method
            or context.normalization_length
            != alignment.normalization.reference_axis_residue_count
            or context.aligned_atom_count
            != alignment.normalization.aligned_atom_count
        ):
            raise ValueError("comparison Observation contradicts its alignment")
    tm_value = float(tm_score.value)
    rmsd_value = float(rmsd.value)
    return ThreeWayComparisonEdge(
        edge_id=edge_id,
        subject=subject,
        reference=reference,
        alignment_evidence_content_digest=alignment_digest,
        alignment_method=alignment.method,
        normalization_length=alignment.normalization.reference_axis_residue_count,
        aligned_atom_count=alignment.normalization.aligned_atom_count,
        tm_score=tm_value,
        rmsd_angstrom=rmsd_value,
        tm_score_method=tm_score.method,
        rmsd_method=rmsd.method,
        tm_score_content_digest=_value_digest(call, tm_score_port),
        rmsd_content_digest=_value_digest(call, rmsd_port),
        close=comparison_is_close(tm_value, rmsd_value),
    )


class ThreeWayConsistencyImplementation:
    """Classify one complete exact three-structure evidence graph."""

    def __init__(self, classification_method: ExactContractReference) -> None:
        self._classification_method = classification_method

    def execute(self, call: OperationCall) -> Mapping[str, object]:
        input_candidate, input_reference = _candidate_scope(
            call,
            "input_structures",
        )
        sequence_candidate, sequence_reference = _candidate_scope(
            call,
            "sequence_parents",
        )
        esmfold2_candidate, esmfold2_reference = _candidate_scope(
            call,
            "esmfold2_structures",
        )
        simplefold_candidate, simplefold_reference = _candidate_scope(
            call,
            "simplefold_structures",
        )
        if (
            sequence_candidate.parent_ids != (input_candidate.candidate_id,)
            or esmfold2_candidate.parent_ids != (sequence_candidate.candidate_id,)
            or simplefold_candidate.parent_ids != (sequence_candidate.candidate_id,)
        ):
            raise ValueError("three-way Candidates do not retain exact lineage")

        sequence = cast(ProteinSequence, sequence_candidate.data).sequence
        residue_count = len(sequence)
        axis_records = (
            _axis(call, "input_residue_axes", input_reference),
            _axis(call, "esmfold2_residue_axes", esmfold2_reference),
            _axis(call, "simplefold_residue_axes", simplefold_reference),
        )
        axes = tuple(axis for axis, _ in axis_records)
        if any(
            axis.layout.length != residue_count or axis.sequence != sequence
            for axis in axes
        ):
            raise ValueError("three-way residue axes do not share one sequence")
        alignment_values = (
            call.inputs["input_esmfold2_alignments"].value,
            call.inputs["input_simplefold_alignments"].value,
            call.inputs["method_alignments"].value,
        )
        if any(len(items) != 1 for items in alignment_values):
            raise ValueError("three-way graph requires exactly three alignments")
        axis_digests = tuple(
            reference.axis_content_digest for _, reference in axis_records
        )
        input_esmfold2_alignment = alignment_values[0][0]
        input_simplefold_alignment = alignment_values[1][0]
        method_alignment = alignment_values[2][0]
        if (
            input_esmfold2_alignment.subject_axis_content_digest
            != axis_digests[1]
            or input_esmfold2_alignment.reference_axis_content_digest
            != axis_digests[0]
            or input_simplefold_alignment.subject_axis_content_digest
            != axis_digests[2]
            or input_simplefold_alignment.reference_axis_content_digest
            != axis_digests[0]
            or method_alignment.subject_axis_content_digest != axis_digests[1]
            or method_alignment.reference_axis_content_digest != axis_digests[2]
        ):
            raise ValueError("three-way alignments contradict their exact axes")

        pairing = cast(
            PairwiseCandidateMapping,
            call.inputs["method_pairing"].value,
        )
        if (
            len(pairing.entries) != 1
            or pairing.entries[0].subject != esmfold2_reference
            or pairing.entries[0].reference != simplefold_reference
        ):
            raise ValueError("Method outputs lack exact sibling pairing")

        confidences = (
            _confidence(
                call,
                role="esmfold2",
                port="esmfold2_confidence",
                subject=esmfold2_reference,
                sequence_parent=sequence_reference,
                residue_count=residue_count,
            ),
            _confidence(
                call,
                role="simplefold",
                port="simplefold_confidence",
                subject=simplefold_reference,
                sequence_parent=sequence_reference,
                residue_count=residue_count,
            ),
        )
        edges = (
            _edge(
                call,
                edge_id="input_esmfold2",
                alignment_port="input_esmfold2_alignments",
                tm_score_port="input_esmfold2_tm_scores",
                rmsd_port="input_esmfold2_rmsd_scores",
                subject=esmfold2_reference,
                reference=input_reference,
            ),
            _edge(
                call,
                edge_id="input_simplefold",
                alignment_port="input_simplefold_alignments",
                tm_score_port="input_simplefold_tm_scores",
                rmsd_port="input_simplefold_rmsd_scores",
                subject=simplefold_reference,
                reference=input_reference,
            ),
            _edge(
                call,
                edge_id="esmfold2_simplefold",
                alignment_port="method_alignments",
                tm_score_port="method_tm_scores",
                rmsd_port="method_rmsd_scores",
                subject=esmfold2_reference,
                reference=simplefold_reference,
            ),
        )
        classification, subreason = classify_three_way_consistency(
            confidences,
            edges,
        )
        return {
            "consistency": ThreeWayConsistencyEvidence(
                input_structure=input_reference,
                sequence_parent=sequence_reference,
                esmfold2_structure=esmfold2_reference,
                simplefold_structure=simplefold_reference,
                classification_method=self._classification_method,
                input_b_factor_semantics=(
                    "uninterpreted_coordinate_temperature_factor"
                ),
                residue_count=residue_count,
                plddt_threshold=70.0,
                tm_score_threshold=0.8,
                rmsd_threshold_angstrom=2.5,
                confidences=confidences,
                edges=edges,
                classification=classification,
                subreason=subreason,
            )
        }
