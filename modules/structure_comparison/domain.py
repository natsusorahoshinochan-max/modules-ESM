"""Nominal immutable values shared by structure-comparison Nodes."""

from __future__ import annotations

from dataclasses import dataclass

from datatypes import ExactContractReference, PairwiseParticipant


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
    """Exact inputs used to interpret correspondence coverage and RMSD."""

    atom_selection: str
    subject_residue_count: int
    reference_residue_count: int
    aligned_atom_count: int
    coverage_denominator: str


@dataclass(frozen=True, slots=True)
class StructureAlignmentEvidence:
    """Versioned complete evidence for one subject-to-reference superposition."""

    schema_version: str
    subject: PairwiseParticipant
    reference: PairwiseParticipant
    correspondence: tuple[AlignmentAtomCorrespondence, ...]
    transform: StructureAlignmentTransform
    normalization: StructureAlignmentNormalization
    method: ExactContractReference


@dataclass(frozen=True, slots=True)
class StructureAlignmentEvidenceCollection:
    """One complete one-to-one collection alignment from an explicit mapping."""

    schema_version: str
    pairing_source: str
    accepted_cardinality: str
    alignments: tuple[StructureAlignmentEvidence, ...]
