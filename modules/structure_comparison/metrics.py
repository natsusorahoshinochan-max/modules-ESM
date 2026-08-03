"""Evidence-only structure-comparison metric projections."""

from __future__ import annotations

import math

from datatypes import PairwiseObservationContext, PairwiseParticipant

from .domain import StructureAlignmentEvidence


def rmsd_from_evidence(evidence: StructureAlignmentEvidence) -> float:
    """Project the validated RMSD already established by alignment evidence."""
    return float(evidence.rmsd)


def tm_score_from_evidence(evidence: StructureAlignmentEvidence) -> float:
    """Compute reference-axis-normalized TM-score from exact residuals only."""
    reference_length = evidence.normalization.reference_axis_residue_count
    d0 = (
        1.24 * (reference_length - 15) ** (1.0 / 3.0) - 1.8
        if reference_length > 15
        else 0.5
    )
    d0 = max(0.5, d0)
    return math.fsum(
        1.0 / (1.0 + (float(entry.residual_distance) / d0) ** 2)
        for entry in evidence.correspondence
    ) / reference_length


def evidence_metric_context(
    evidence: StructureAlignmentEvidence,
    *,
    evidence_content_digest: str,
    pairing_mode: str,
    metric_kind: str,
) -> PairwiseObservationContext:
    """Build the exact provenance Context for one evidence-only projection."""
    if metric_kind == "tm_score":
        normalization = "reference-axis-residue-count"
        normalization_length = (
            evidence.normalization.reference_axis_residue_count
        )
    elif metric_kind == "rmsd":
        normalization = "aligned-CA-mean-square-distance"
        normalization_length = evidence.normalization.aligned_atom_count
    else:
        raise ValueError("unknown structure-comparison evidence metric")
    return PairwiseObservationContext(
        subject=PairwiseParticipant(
            role="subject",
            candidate=evidence.subject,
        ),
        reference=PairwiseParticipant(
            role="reference",
            candidate=evidence.reference,
        ),
        pairing_mode=pairing_mode,
        normalization=normalization,
        evidence_content_digest=evidence_content_digest,
        evidence_method=evidence.method,
        subject_axis_content_digest=evidence.subject_axis_content_digest,
        reference_axis_content_digest=evidence.reference_axis_content_digest,
        normalization_length=normalization_length,
        aligned_atom_count=evidence.normalization.aligned_atom_count,
    )
