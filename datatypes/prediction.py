"""Provider-independent structure-prediction confidence values."""

from __future__ import annotations

from dataclasses import dataclass
import re

from datatypes.candidate import CandidateDataReference
from datatypes.exact_reference import (
    ExactContractReference,
    ExactPortValueReference,
    ResidueAxisReference,
)
from datatypes.identifier import validate_canonical_identifier
from datatypes.i_json import canonical_sha256
from datatypes.residue import ResidueLayout
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure


_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991

def _require_content_digest(value: object, *, field_name: str) -> str:
    if type(value) is not str or _CONTENT_DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical sha256 digest")
    return value


def prediction_key(
    *,
    output_role: str,
    output_slot: int,
    structure_content_digest: str,
    prediction_axis_content_digest: str,
) -> str:
    """Identify one subjectless fact by its exact future Candidate join facts."""
    validate_canonical_identifier(output_role, "output_role")
    if (
        type(output_slot) is not int
        or not 0 <= output_slot <= _I_JSON_INTEGER_LIMIT
    ):
        raise ValueError("output_slot must be a nonnegative I-JSON integer")
    _require_content_digest(
        structure_content_digest,
        field_name="structure_content_digest",
    )
    _require_content_digest(
        prediction_axis_content_digest,
        field_name="prediction_axis_content_digest",
    )
    digest = canonical_sha256(
        {
            "schema_namespace": (
                "protein-workbench-structure-prediction-key/v1"
            ),
            "output_role": output_role,
            "output_slot": output_slot,
            "structure_content_digest": structure_content_digest,
            "prediction_axis_content_digest": (
                prediction_axis_content_digest
            ),
        }
    )
    return f"prediction-{digest.removeprefix('sha256:')}"


@dataclass(frozen=True, slots=True)
class PredictionResidueAxis:
    """The exact input residue population used by one structure prediction."""

    source: CandidateDataReference | ExactPortValueReference
    layout: ResidueLayout
    sequence: ProteinSequence


@dataclass(frozen=True, slots=True)
class PendingConfidenceFact:
    """Provider result awaiting canonical structure and axis identities."""

    candidate_id: str
    output_role: str
    output_slot: int
    structure: ProteinStructure
    prediction_axis: PredictionResidueAxis
    plddt_per_residue: tuple[float | None, ...]
    ptm: float | None
    pae: tuple[tuple[float, ...], ...] | None


@dataclass(frozen=True, slots=True)
class PendingConfidenceFactCollection:
    """Data-only confidence relation awaiting admission-owned identities."""

    observation_method: ExactContractReference
    entries: tuple[PendingConfidenceFact, ...]


@dataclass(frozen=True, slots=True)
class MaterializedConfidenceFact:
    """One final confidence fact and its exact admission projections."""

    candidate_id: str
    prediction_key: str
    fact: ConfidenceFact
    scientific_axis: ResidueAxisReference


def prediction_axis_reference(
    axis: PredictionResidueAxis,
    *,
    axis_contract: ExactContractReference,
    axis_content_digest: str,
) -> ResidueAxisReference:
    """Project one prediction axis using its codec-owned exact identity."""
    return ResidueAxisReference(
        axis_kind="prediction_input",
        axis_contract=axis_contract,
        axis_content_digest=axis_content_digest,
        source=axis.source,
        layout=axis.layout,
    )



@dataclass(frozen=True, slots=True)
class ConfidenceFact:
    """Subjectless prediction confidence awaiting exact Candidate admission."""

    prediction_key: str
    structure_content_digest: str
    prediction_axis: PredictionResidueAxis
    plddt_per_residue: tuple[float | None, ...]
    ptm: float | None
    pae: tuple[tuple[float, ...], ...] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "plddt_per_residue", tuple(
            float(value) if type(value) is int else value
            for value in self.plddt_per_residue
        ))
        if type(self.ptm) is int:
            object.__setattr__(self, "ptm", float(self.ptm))
        if self.pae is not None:
            object.__setattr__(self, "pae", tuple(
                tuple(float(value) if type(value) is int else value for value in row)
                for row in self.pae
            ))


@dataclass(frozen=True, slots=True)
class ConfidenceFactCollection:
    """Canonical facts produced by one exact observation Method."""

    observation_method: ExactContractReference
    entries: tuple[ConfidenceFact, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(sorted(
            self.entries, key=lambda entry: entry.prediction_key
        )))


def materialize_confidence_fact(
    pending: PendingConfidenceFact,
    *,
    structure_content_digest: str,
    prediction_axis_contract: ExactContractReference,
    prediction_axis_content_digest: str,
) -> MaterializedConfidenceFact:
    """Bind trusted encoded identities to one provider confidence result."""
    key = prediction_key(
        output_role=pending.output_role,
        output_slot=pending.output_slot,
        structure_content_digest=structure_content_digest,
        prediction_axis_content_digest=prediction_axis_content_digest,
    )
    return MaterializedConfidenceFact(
        candidate_id=pending.candidate_id,
        prediction_key=key,
        fact=ConfidenceFact(
            prediction_key=key,
            structure_content_digest=structure_content_digest,
            prediction_axis=pending.prediction_axis,
            plddt_per_residue=pending.plddt_per_residue,
            ptm=pending.ptm,
            pae=pending.pae,
        ),
        scientific_axis=prediction_axis_reference(
            pending.prediction_axis,
            axis_contract=prediction_axis_contract,
            axis_content_digest=prediction_axis_content_digest,
        ),
    )
