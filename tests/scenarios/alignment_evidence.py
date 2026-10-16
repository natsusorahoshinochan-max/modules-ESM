"""Hand-authored alignment evidence shared by metric and admission contracts."""

from __future__ import annotations

from datatypes.candidate import CandidateDataReference
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


def _evidence() -> StructureAlignmentEvidence:
    return StructureAlignmentEvidence(
        subject=CandidateDataReference(
            candidate_id="subject",
            data_type_id="protein.structure",
            content_digest="sha256:" + "1" * 64,
        ),
        reference=CandidateDataReference(
            candidate_id="reference",
            data_type_id="protein.structure",
            content_digest="sha256:" + "2" * 64,
        ),
        subject_axis_content_digest="sha256:" + "3" * 64,
        reference_axis_content_digest="sha256:" + "4" * 64,
        segment_map=(
            AlignmentSegmentMapEntry(
                subject_segment_index=0,
                reference_segment_index=0,
                subject_chain_id="S",
                reference_chain_id="R",
                sequence_score=16,
                paired_residue_count=2,
                cigar="MM",
            ),
        ),
        policy=AlignmentCorrespondencePolicy(
            kind="sequence_primary_affine",
            pin_matching_chain_ids=False,
        ),
        correspondence=(
            AlignmentAtomCorrespondence(
                subject_residue_id="S:1",
                subject_atom_name="CA",
                subject_coordinate=(0.0, 0.0, 0.0),
                reference_residue_id="R:1",
                reference_atom_name="CA",
                reference_coordinate=(0.0, 0.0, 0.0),
                transformed_subject_coordinate=(0.0, 0.0, 0.0),
                residual_distance=0.0,
            ),
            AlignmentAtomCorrespondence(
                subject_residue_id="S:2",
                subject_atom_name="CA",
                subject_coordinate=(1.0, 0.0, 0.0),
                reference_residue_id="R:2",
                reference_atom_name="CA",
                reference_coordinate=(2.0, 0.0, 0.0),
                transformed_subject_coordinate=(1.0, 0.0, 0.0),
                residual_distance=1.0,
            ),
        ),
        transform=StructureAlignmentTransform(
            maps_from_role="subject",
            maps_to_role="reference",
            row_vector_rotation=(
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ),
            translation=(0.0, 0.0, 0.0),
        ),
        normalization=StructureAlignmentNormalization(
            subject_axis_residue_count=2,
            reference_axis_residue_count=20,
            subject_ca_count=2,
            reference_ca_count=20,
            aligned_atom_count=2,
        ),
        rmsd=2**-0.5,
        coverage=0.1,
        method=SEQUENCE_PRIMARY_AFFINE_METHOD_REFERENCE,
    )
