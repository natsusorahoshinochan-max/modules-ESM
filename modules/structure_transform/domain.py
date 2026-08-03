"""Candidate-associated scientific values owned by structure transformation."""

from __future__ import annotations

from dataclasses import dataclass

from datatypes import (
    CandidateDataReference,
    ModifiedResidueNormalizationCollection,
    ResolvedStructureResidueAxis,
)


def _association_key(subject: CandidateDataReference) -> tuple[str, str, str]:
    return (
        subject.candidate_id,
        subject.data_type_id,
        subject.content_digest,
    )


@dataclass(frozen=True, slots=True)
class CandidateResolvedResidueAxisAssociation:
    """One resolved axis bound to exact Candidate structure content."""

    subject: CandidateDataReference
    residue_axis: ResolvedStructureResidueAxis


@dataclass(frozen=True, slots=True)
class CandidateResolvedResidueAxisAssociations:
    """Canonical reference-addressed collection of resolved residue axes."""

    entries: tuple[CandidateResolvedResidueAxisAssociation, ...] = ()

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if any(
            type(entry) is not CandidateResolvedResidueAxisAssociation
            for entry in entries
        ):
            raise TypeError(
                "entries must be CandidateResolvedResidueAxisAssociation values"
            )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda entry: _association_key(entry.subject))),
        )

    def axis_for(
        self,
        subject: CandidateDataReference,
    ) -> ResolvedStructureResidueAxis:
        """Return the axis bound to one exact Candidate data reference."""
        for entry in self.entries:
            if entry.subject == subject:
                return entry.residue_axis
        raise KeyError(
            "resolved residue-axis associations contain no exact Candidate "
            f"reference {subject.candidate_id}"
        )


@dataclass(frozen=True, slots=True)
class CandidateModifiedResidueNormalizationAssociation:
    """One normalization set bound to exact Candidate structure content."""

    subject: CandidateDataReference
    normalizations: ModifiedResidueNormalizationCollection


@dataclass(frozen=True, slots=True)
class CandidateModifiedResidueNormalizationAssociations:
    """Canonical reference-addressed collection of normalization sets."""

    entries: tuple[
        CandidateModifiedResidueNormalizationAssociation,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if any(
            type(entry)
            is not CandidateModifiedResidueNormalizationAssociation
            for entry in entries
        ):
            raise TypeError(
                "entries must be "
                "CandidateModifiedResidueNormalizationAssociation values"
            )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda entry: _association_key(entry.subject))),
        )

    def normalizations_for(
        self,
        subject: CandidateDataReference,
    ) -> ModifiedResidueNormalizationCollection:
        """Return normalizations bound to one exact Candidate data reference."""
        for entry in self.entries:
            if entry.subject == subject:
                return entry.normalizations
        raise KeyError(
            "modified-residue normalization associations contain no exact "
            f"Candidate reference {subject.candidate_id}"
        )
