"""Explicit scientific conversions for protein structures."""

from .domain import (
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
)
from .package import MODULE_PACKAGE

__all__ = [
    "CandidateModifiedResidueNormalizationAssociation",
    "CandidateModifiedResidueNormalizationAssociations",
    "CandidateResolvedResidueAxisAssociation",
    "CandidateResolvedResidueAxisAssociations",
    "MODULE_PACKAGE",
]
