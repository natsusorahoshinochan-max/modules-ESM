"""Package-local values for identity-aligned structure annotations."""

from __future__ import annotations

from dataclasses import dataclass

from datatypes import CandidateDataReference, ResidueLayout


@dataclass(frozen=True, slots=True)
class DSSPAnnotation:
    """One DSSP result reconciled to an exact structure residue layout."""

    subject: CandidateDataReference
    layout: ResidueLayout
    secondary_structure: tuple[str, ...]
    sasa: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class StructureAnnotationTrack:
    """One annotation track carrying the exact layout it describes."""

    subject: CandidateDataReference
    layout: ResidueLayout
    values: tuple[str | float | None, ...]
