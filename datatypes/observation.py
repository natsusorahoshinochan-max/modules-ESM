"""Provider-independent scientific Observation values."""

from __future__ import annotations

from dataclasses import dataclass
import re

from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import ExactContractReference, ResidueAxisReference
from datatypes.i_json import FrozenList, freeze_i_json, i_json_values_equal


def _ordered_list(value: object, *, field_name: str) -> FrozenList:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return FrozenList(value)


@dataclass(frozen=True, slots=True)
class IntrinsicObservationContext:
    """The one closed Context for an intrinsic Candidate measurement."""

    kind: str = "intrinsic"

@dataclass(frozen=True, slots=True)
class CalibrationObservationContext:
    """A fixed population baseline required to interpret an Observation."""

    calibration_metric: str
    calibration_value: float
    calibration_unit: str
    population_id: str
    kind: str = "calibration"

@dataclass(frozen=True, slots=True)
class PairwiseCandidateMatch:
    """One explicit subject-to-reference Candidate relationship."""

    subject: CandidateDataReference
    reference: CandidateDataReference

    def __post_init__(self) -> None:
        if type(self.subject) is not CandidateDataReference:
            raise TypeError(
                "subject must be an exact CandidateDataReference"
            )
        if type(self.reference) is not CandidateDataReference:
            raise TypeError(
                "reference must be an exact CandidateDataReference"
            )


@dataclass(frozen=True, slots=True)
class PairwiseCandidateMapping:
    """Closed per-subject counterpart mapping carried through a typed Port."""

    entries: tuple[PairwiseCandidateMatch, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entries",
            _ordered_list(self.entries, field_name="entries"),
        )


@dataclass(frozen=True, slots=True)
class PairwiseParticipant:
    """One role-labelled Candidate participating in a pairwise observation."""

    role: str
    candidate: CandidateDataReference

    def __post_init__(self) -> None:
        if type(self.candidate) is not CandidateDataReference:
            raise TypeError(
                "candidate must be an exact CandidateDataReference"
            )

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    @property
    def data_type_id(self) -> str:
        return self.candidate.data_type_id

    @property
    def content_digest(self) -> str:
        return self.candidate.content_digest

@dataclass(frozen=True, slots=True)
class PairwiseObservationContext:
    """Exact subject/reference relationship defining a pairwise observation."""

    subject: PairwiseParticipant
    reference: PairwiseParticipant
    pairing_mode: str
    normalization: str
    kind: str = "pairwise"
    evidence_content_digest: str | None = None
    evidence_method: ExactContractReference | None = None
    subject_axis_content_digest: str | None = None
    reference_axis_content_digest: str | None = None
    normalization_length: int | None = None
    aligned_atom_count: int | None = None

    def __post_init__(self) -> None:
        evidence = (
            self.evidence_content_digest,
            self.evidence_method,
            self.normalization_length,
            self.aligned_atom_count,
        )
        axis_evidence = (
            self.subject_axis_content_digest,
            self.reference_axis_content_digest,
        )
        if all(item is None for item in evidence):
            if any(item is not None for item in axis_evidence):
                raise ValueError(
                    "Pairwise Context requires complete exact axis provenance"
                )
            return
        if (
            any(item is None for item in evidence)
            or not isinstance(self.evidence_content_digest, str)
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                self.evidence_content_digest,
            )
            is None
            or type(self.evidence_method) is not ExactContractReference
            or self.evidence_method.contract_kind != "method"
            or type(self.normalization_length) is not int
            or self.normalization_length < 1
            or type(self.aligned_atom_count) is not int
            or self.aligned_atom_count < 1
            or self.aligned_atom_count > self.normalization_length
        ):
            raise ValueError(
                "Pairwise Context requires complete exact evidence provenance"
            )
        if any(item is not None for item in axis_evidence) and (
            any(item is None for item in axis_evidence)
            or self.evidence_content_digest is None
            or any(
                type(item) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", item) is None
                for item in axis_evidence
            )
        ):
            raise ValueError(
                "Pairwise Context requires complete exact axis provenance"
            )

@dataclass(frozen=True, slots=True)
class ScoreObservation:
    """A scientifically typed Candidate measurement.

    ``value`` is interpreted by the exact Metric, Method, and Context but is
    intentionally excluded from ``identity``.
    """

    subject: CandidateDataReference
    metric: ExactContractReference
    method: ExactContractReference
    context: (
        IntrinsicObservationContext
        | CalibrationObservationContext
        | PairwiseObservationContext
    )
    source_partition: str
    value: object
    residue_axis: ResidueAxisReference | None = None

    def __post_init__(self) -> None:
        if type(self.subject) is not CandidateDataReference:
            raise TypeError(
                "subject must be an exact CandidateDataReference"
            )
        if self.residue_axis is not None and type(
            self.residue_axis
        ) is not ResidueAxisReference:
            raise TypeError(
                "residue_axis must be an exact ResidueAxisReference"
            )
        object.__setattr__(self, "value", freeze_i_json(self.value))

    @property
    def candidate_id(self) -> str:
        """Return the Candidate ID derived from the exact subject."""
        return self.subject.candidate_id

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.subject,
            self.metric,
            self.method,
            self.context,
            self.residue_axis,
        )


@dataclass(frozen=True, slots=True)
class ScoreCollection:
    """Ordered scientifically typed v2 Score Observations."""

    collection_id: str
    entries: tuple[ScoreObservation, ...] = ()

    def __post_init__(self) -> None:
        entries = _ordered_list(self.entries, field_name="entries")
        by_identity: dict[tuple[object, ...], ScoreObservation] = {}
        for entry in entries:
            if type(entry) is not ScoreObservation:
                raise TypeError(
                    "entries must contain exact Score Observations"
                )
            existing = by_identity.get(entry.identity)
            if existing is None:
                by_identity[entry.identity] = entry
                continue
            if not i_json_values_equal(existing.value, entry.value):
                raise ValueError(
                    "Score Collection contains one Observation identity "
                    "with conflicting values"
                )
            if existing.source_partition != entry.source_partition:
                raise ValueError(
                    "Score Collection contains an Observation identity "
                    "partition collision"
                )
        object.__setattr__(self, "entries", entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)
