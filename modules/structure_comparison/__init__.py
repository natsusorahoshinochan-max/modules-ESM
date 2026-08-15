"""Candidate-associated structure-comparison domain and v4 production wiring."""

from .domain import (
    AlignmentAtomCorrespondence,
    AlignmentCorrespondencePolicy,
    AlignmentSegmentMapEntry,
    AtomPairDistanceEvidence,
    InsertedLoopCandidateEvidence,
    InsertedLoopEvaluationCollection,
    InsertedLoopThresholds,
    ResidueIdentityCorrespondence,
    ResolvedAxisAlignment,
    StructureAlignmentEvidence,
    StructureAlignmentNormalization,
    StructureAlignmentTransform,
)
from .package import MODULE_PACKAGE
__all__ = [
    "AlignmentAtomCorrespondence",
    "AlignmentCorrespondencePolicy",
    "AlignmentSegmentMapEntry",
    "AtomPairDistanceEvidence",
    "InsertedLoopCandidateEvidence",
    "InsertedLoopEvaluationCollection",
    "InsertedLoopThresholds",
    "MODULE_PACKAGE",
    "ResolvedAxisAlignment",
    "ResidueIdentityCorrespondence",
    "StructureAlignmentEvidence",
    "StructureAlignmentNormalization",
    "StructureAlignmentTransform",
]
