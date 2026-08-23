"""Candidate-associated scientific values owned by structure transformation."""

from __future__ import annotations

from dataclasses import dataclass

from core.catalog.canonical import canonical_sha256

from datatypes.candidate import CandidateDataReference
from datatypes.residue import ModifiedResidueNormalizationCollection
from datatypes.structure import ProteinStructure, ResolvedStructureResidueAxis


def normalization_key(
    *,
    output_role: str,
    output_slot: int,
    structure_content_digest: str,
    normalizations_content_digest: str,
) -> str:
    """Bind one subjectless normalization fact to its future output slot."""
    digest = canonical_sha256(
        {
            "schema_namespace": (
                "protein-workbench-candidate-normalization-key/v1"
            ),
            "output_role": output_role,
            "output_slot": output_slot,
            "structure_content_digest": structure_content_digest,
            "normalizations_content_digest": normalizations_content_digest,
        }
    )
    return f"normalization-{digest.removeprefix('sha256:')}"


@dataclass(frozen=True, slots=True)
class CandidateNormalizationFact:
    """Subjectless normalization evidence awaiting Candidate admission."""

    normalization_key: str
    structure_content_digest: str
    normalizations: ModifiedResidueNormalizationCollection


@dataclass(frozen=True, slots=True)
class PendingCandidateNormalizationFact:
    """Normalization evidence awaiting canonical source identities."""

    candidate_id: str
    output_role: str
    output_slot: int
    structure: ProteinStructure
    normalizations: ModifiedResidueNormalizationCollection


@dataclass(frozen=True, slots=True)
class PendingCandidateNormalizationFactCollection:
    """Data-only normalization relation awaiting admission identities."""

    entries: tuple[PendingCandidateNormalizationFact, ...]


@dataclass(frozen=True, slots=True)
class MaterializedCandidateNormalizationFact:
    """One final normalization fact and its Candidate metadata identity."""

    candidate_id: str
    normalization_key: str
    fact: CandidateNormalizationFact


def materialize_candidate_normalization_fact(
    pending: PendingCandidateNormalizationFact,
    *,
    structure_content_digest: str,
    normalizations_content_digest: str,
) -> MaterializedCandidateNormalizationFact:
    """Bind trusted encoded identities to one normalization result."""
    key = normalization_key(
        output_role=pending.output_role,
        output_slot=pending.output_slot,
        structure_content_digest=structure_content_digest,
        normalizations_content_digest=normalizations_content_digest,
    )
    return MaterializedCandidateNormalizationFact(
        candidate_id=pending.candidate_id,
        normalization_key=key,
        fact=CandidateNormalizationFact(
            normalization_key=key,
            structure_content_digest=structure_content_digest,
            normalizations=pending.normalizations,
        ),
    )


@dataclass(frozen=True, slots=True)
class CandidateNormalizationFactCollection:
    """Canonical output-slot-addressed normalization facts."""

    entries: tuple[CandidateNormalizationFact, ...]

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(entries, key=lambda entry: entry.normalization_key)),
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
