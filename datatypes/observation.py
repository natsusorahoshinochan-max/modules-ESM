"""Provider-independent scientific Observation values."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal

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
class CandidateRelationEntry:
    """One explicit subject-to-reference Candidate relationship."""

    subject: CandidateDataReference
    reference: CandidateDataReference



@dataclass(frozen=True, slots=True)
class CandidateRelation:
    """One exact reference per subject with reference reuse allowed."""

    entries: tuple[CandidateRelationEntry, ...] = ()

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
    sequence_correspondence: tuple[tuple[int, str], ...] | None = field(
        default=None, metadata={"wire_optional": True},
    )

    subject_region: tuple[str, ...] | None = field(default=None, metadata={"wire_optional": True})
    reference_region: tuple[str, ...] | None = field(default=None, metadata={"wire_optional": True})

    def __post_init__(self) -> None:
        for name in ('subject_region', 'reference_region'):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, FrozenList(value))
        if self.sequence_correspondence is not None:
            object.__setattr__(self, "sequence_correspondence", FrozenList(
                FrozenList(pair) for pair in self.sequence_correspondence
            ))


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
        unique: list[ScoreObservation] = []
        by_identity: dict[tuple[object, ...], ScoreObservation] = {}
        for entry in entries:
            if type(entry) is ScoreObservation:
                existing = by_identity.get(entry.identity)
                if existing is not None and (
                    existing.source_partition == entry.source_partition
                    and i_json_values_equal(existing.value, entry.value)
                ):
                    continue
                by_identity[entry.identity] = entry
            unique.append(entry)
        object.__setattr__(self, "entries", FrozenList(unique))

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)


def validate_pairwise_evidence(value: PairwiseObservationContext) -> None:
    evidence = (
        value.evidence_content_digest,
        value.evidence_method,
        value.normalization_length,
        value.aligned_atom_count,
    )
    axis_evidence = (
        value.subject_axis_content_digest,
        value.reference_axis_content_digest,
    )
    if all(item is None for item in evidence):
        if any(item is not None for item in axis_evidence):
            raise ValueError(
                "Pairwise Context requires complete exact axis provenance"
            )
        return
    if (
        any(item is None for item in evidence)
        or not isinstance(value.evidence_content_digest, str)
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            value.evidence_content_digest,
        )
        is None
        or type(value.evidence_method) is not ExactContractReference
        or value.evidence_method.contract_kind != "method"
        or type(value.normalization_length) is not int
        or value.normalization_length < 1
        or type(value.aligned_atom_count) is not int
        or value.aligned_atom_count < 1
        or value.aligned_atom_count > value.normalization_length
    ):
        raise ValueError(
            "Pairwise Context requires complete exact evidence provenance"
        )
    if any(item is not None for item in axis_evidence) and (
        any(item is None for item in axis_evidence)
        or value.evidence_content_digest is None
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
class IntrinsicContextProfile:
    """Fixed scientific intrinsic Observation Context contract."""

    kind: Literal["intrinsic"] = "intrinsic"


@dataclass(frozen=True, slots=True)
class CalibrationContextProfile:
    """Fixed scientific calibration Observation Context contract."""

    calibration_metric: str
    calibration_value: int | float
    calibration_unit: str
    population_id: str
    kind: Literal["calibration"] = "calibration"


@dataclass(frozen=True, slots=True)
class PairwiseContextProfile:
    """Fixed scientific pairwise Observation Context contract."""

    subject_role: str
    reference_role: str
    pairing_mode: str
    normalization: str
    kind: Literal["pairwise"] = "pairwise"


ObservationContextProfile = (
    IntrinsicContextProfile
    | CalibrationContextProfile
    | PairwiseContextProfile
)


def observation_context_profile(context: IntrinsicObservationContext | CalibrationObservationContext | PairwiseObservationContext) -> ObservationContextProfile:
    """Extract fixed conditions from an admitted actual Observation Context."""
    if isinstance(context, IntrinsicObservationContext):
        return IntrinsicContextProfile()
    if isinstance(context, CalibrationObservationContext):
        return CalibrationContextProfile(
            context.calibration_metric, context.calibration_value,
            context.calibration_unit, context.population_id,
        )
    return PairwiseContextProfile(
        context.subject.role, context.reference.role,
        context.pairing_mode, context.normalization,
    )


def observation_context_profile_descriptor(profile: ObservationContextProfile) -> dict[str, Any]:
    """Project fixed scientific conditions without admitting them again."""
    if isinstance(profile, IntrinsicContextProfile):
        return {"kind": profile.kind}
    if isinstance(profile, CalibrationContextProfile):
        return {
            "kind": profile.kind,
            "calibration_metric": profile.calibration_metric,
            "calibration_value": profile.calibration_value,
            "calibration_unit": profile.calibration_unit,
            "population_id": profile.population_id,
        }
    return {
        "kind": profile.kind,
        "subject_role": profile.subject_role,
        "reference_role": profile.reference_role,
        "pairing_mode": profile.pairing_mode,
        "normalization": profile.normalization,
    }
