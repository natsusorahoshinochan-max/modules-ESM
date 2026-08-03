"""Candidate-associated structure-comparison domain and v4 production wiring."""

from .domain import (
    AlignmentAtomCorrespondence,
    AlignmentCorrespondencePolicy,
    AlignmentSegmentMapEntry,
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
    "MODULE_PACKAGE",
    "ResolvedAxisAlignment",
    "StructureAlignmentEvidence",
    "StructureAlignmentNormalization",
    "StructureAlignmentTransform",
]
