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
