"""Nominal immutable values shared by structure-comparison Nodes."""

from __future__ import annotations

from dataclasses import dataclass

from datatypes import CandidateDataReference, ExactContractReference


Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]


@dataclass(frozen=True, slots=True)
class AlignmentAtomCorrespondence:
    """One exact role-labelled atom pair and its post-transform residual."""

    subject_residue_id: str
    subject_atom_name: str
    subject_coordinate: Vector3
    reference_residue_id: str
    reference_atom_name: str
    reference_coordinate: Vector3
    transformed_subject_coordinate: Vector3
    residual_distance: float


@dataclass(frozen=True, slots=True)
class StructureAlignmentTransform:
    """The row-vector rigid transform mapping subject coordinates to reference."""

    maps_from_role: str
    maps_to_role: str
    row_vector_rotation: Matrix3
    translation: Vector3


@dataclass(frozen=True, slots=True)
class StructureAlignmentNormalization:
    """Exact resolved-axis and admitted-CA normalization counts."""

    subject_axis_residue_count: int
    reference_axis_residue_count: int
    subject_ca_count: int
    reference_ca_count: int
    aligned_atom_count: int


@dataclass(frozen=True, slots=True)
class StructureAlignmentEvidence:
    """Candidate-associated v4 evidence for one exact superposition."""

    subject: CandidateDataReference
    reference: CandidateDataReference
    subject_axis_content_digest: str
    reference_axis_content_digest: str
    segment_map: tuple[AlignmentSegmentMapEntry, ...]
    policy: AlignmentCorrespondencePolicy
    correspondence: tuple[AlignmentAtomCorrespondence, ...]
    transform: StructureAlignmentTransform
    normalization: StructureAlignmentNormalization
    rmsd: float
    coverage: float
    method: ExactContractReference


@dataclass(frozen=True, slots=True)
class AlignmentSegmentMapEntry:
    """One deterministic subject-to-reference segment assignment."""

    subject_segment_index: int
    reference_segment_index: int
    subject_chain_id: str
    reference_chain_id: str
    sequence_score: int | None
    paired_residue_count: int
    cigar: str


@dataclass(frozen=True, slots=True)
class AlignmentCorrespondencePolicy:
    """The exact residue-correspondence policy used before superposition."""

    kind: str
    pin_matching_chain_ids: bool


@dataclass(frozen=True, slots=True)
class ResolvedAxisAlignment:
    """Pure alignment result before Candidate-associated evidence wrapping."""

    segment_map: tuple[AlignmentSegmentMapEntry, ...]
    policy: AlignmentCorrespondencePolicy
    correspondence: tuple[AlignmentAtomCorrespondence, ...]
    transform: StructureAlignmentTransform
    normalization: StructureAlignmentNormalization
    rmsd: float
    coverage: float


@dataclass(frozen=True, slots=True)
class ThreeWayConfidenceEvidence:
    """One Method-specific confidence gate used by three-way classification."""

    role: str
    subject: CandidateDataReference
    method: ExactContractReference
    mean_residue_plddt: float
    eligible: bool
    score_content_digest: str


@dataclass(frozen=True, slots=True)
class ThreeWayComparisonEdge:
    """One explicit thresholded edge in the three-structure graph."""

    edge_id: str
    subject: CandidateDataReference
    reference: CandidateDataReference
    alignment_evidence_content_digest: str
    alignment_method: ExactContractReference
    normalization_length: int
    aligned_atom_count: int
    tm_score: float
    rmsd_angstrom: float
    tm_score_method: ExactContractReference
    rmsd_method: ExactContractReference
    tm_score_content_digest: str
    rmsd_content_digest: str
    close: bool


@dataclass(frozen=True, slots=True)
class ThreeWayConsistencyEvidence:
    """Closed scientific conclusion for input/ESMFold2/SimpleFold agreement."""

    input_structure: CandidateDataReference
    sequence_parent: CandidateDataReference
    esmfold2_structure: CandidateDataReference
    simplefold_structure: CandidateDataReference
    classification_method: ExactContractReference
    input_b_factor_semantics: str
    residue_count: int
    plddt_threshold: float
    tm_score_threshold: float
    rmsd_threshold_angstrom: float
    confidences: tuple[ThreeWayConfidenceEvidence, ...]
    edges: tuple[ThreeWayComparisonEdge, ...]
    classification: str
    subreason: str | None


def confidence_is_eligible(mean_residue_plddt: float) -> bool:
    """Apply the exact inclusive confidence threshold."""
    return mean_residue_plddt >= 70.0


def comparison_is_close(tm_score: float, rmsd_angstrom: float) -> bool:
    """Apply both exact inclusive pairwise-closeness thresholds."""
    return tm_score >= 0.8 and rmsd_angstrom <= 2.5


def classify_three_way_consistency(
    confidences: tuple[ThreeWayConfidenceEvidence, ...],
    edges: tuple[ThreeWayComparisonEdge, ...],
) -> tuple[str, str | None]:
    """Classify the exact threshold graph encoded by the evidence value."""
    if not all(item.eligible for item in confidences):
        return "insufficient_evidence", "method_confidence_below_threshold"
    close = {edge.edge_id for edge in edges if edge.close}
    if len(close) == 3:
        return "three_way_consistent", None
    if len(close) == 2:
        return "insufficient_evidence", "threshold_boundary_nontransitive"
    if not close:
        return "all_disagree", None
    if close == {"esmfold2_simplefold"}:
        return "input_disagreement", None
    return "method_disagreement", None
