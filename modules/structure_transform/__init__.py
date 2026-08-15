"""Explicit scientific conversions for protein structures."""

from .domain import (
    CandidateNormalizationFact,
    CandidateNormalizationFactCollection,
    CandidateModifiedResidueNormalizationAssociation,
    CandidateModifiedResidueNormalizationAssociations,
    CandidateResolvedResidueAxisAssociation,
    CandidateResolvedResidueAxisAssociations,
    normalization_key,
)
from .package import MODULE_PACKAGE

__all__ = [
    "CandidateNormalizationFact",
    "CandidateNormalizationFactCollection",
    "CandidateModifiedResidueNormalizationAssociation",
    "CandidateModifiedResidueNormalizationAssociations",
    "CandidateResolvedResidueAxisAssociation",
    "CandidateResolvedResidueAxisAssociations",
    "MODULE_PACKAGE",
    "normalization_key",
]
