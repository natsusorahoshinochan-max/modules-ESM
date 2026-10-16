"""Focused v3 tests for evidence-only RMSD and TM-score projections."""

from __future__ import annotations

from tests.scenarios.alignment_evidence import (
    _evidence,
)

import pytest

from datatypes.candidate import CandidateDataReference
from datatypes.observation import PairwiseParticipant
from modules.structure_comparison.contracts import (
    SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
)
from modules.structure_comparison.domain import (
    AlignmentAtomCorrespondence,
    AlignmentCorrespondencePolicy,
    AlignmentSegmentMapEntry,
    StructureAlignmentEvidence,
    StructureAlignmentNormalization,
    StructureAlignmentTransform,
)
from modules.structure_comparison.metrics import (
    evidence_metric_context,
    rmsd_from_evidence,
    tm_score_from_evidence,
)




def test_tm_score_uses_evidence_residuals_and_reference_axis_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "tmtools.tm_align",
        lambda *args, **kwargs: pytest.fail("metric must not invoke tm_align"),
    )
    evidence = _evidence()
    d0 = max(0.5, 1.24 * (20 - 15) ** (1.0 / 3.0) - 1.8)

    score = tm_score_from_evidence(evidence)

    assert score == pytest.approx(
        (1.0 + 1.0 / (1.0 + (1.0 / d0) ** 2)) / 20
    )
    assert rmsd_from_evidence(evidence) == pytest.approx(2**-0.5)


def test_metric_context_carries_exact_alignment_evidence_provenance() -> None:
    evidence = _evidence()
    evidence_digest = "sha256:" + "5" * 64

    context = evidence_metric_context(
        evidence,
        evidence_content_digest=evidence_digest,
        pairing_mode="fixed_reference",
        metric_kind="tm_score",
    )

    assert context.subject == PairwiseParticipant(
        role="subject",
        candidate=evidence.subject,
    )
    assert context.reference == PairwiseParticipant(
        role="reference",
        candidate=evidence.reference,
    )
    assert context.evidence_content_digest == evidence_digest
    assert context.evidence_method == evidence.method
    assert (
        context.subject_axis_content_digest
        == evidence.subject_axis_content_digest
    )
    assert (
        context.reference_axis_content_digest
        == evidence.reference_axis_content_digest
    )
    assert context.normalization == "reference-axis-residue-count"
    assert context.normalization_length == 20
    assert context.aligned_atom_count == 2


def test_rmsd_context_uses_aligned_ca_normalization() -> None:
    evidence = _evidence()

    context = evidence_metric_context(
        evidence,
        evidence_content_digest="sha256:" + "6" * 64,
        pairing_mode="explicit_relation",
        metric_kind="rmsd",
    )

    assert context.normalization == "aligned-CA-mean-square-distance"
    assert context.normalization_length == 2
    assert context.aligned_atom_count == 2
