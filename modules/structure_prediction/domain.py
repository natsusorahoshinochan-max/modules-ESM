"""Provider-independent structure-prediction confidence values."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from core import builtin_frozen_catalog, canonical_sha256
from datatypes import (
    CandidateDataReference,
    ExactContractReference,
    ExactPortValueReference,
    ProteinSequence,
    ResidueLayout,
    validate_canonical_identifier,
)
from datatypes.protein import validate_protein_sequence, validate_residue_layout
from modules.prompt_authoring.prompt_types import PROTEIN_PROMPT_PORT_TYPE


_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PREDICTION_KEY = re.compile(r"^prediction-[0-9a-f]{64}$")
_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"
)
_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991
_SEQUENCE_PORT_TYPE = builtin_frozen_catalog().require_port_type(
    "protein.sequence",
    "3.0.0",
)
_ALLOWED_SCALAR_SOURCES = {
    ExactContractReference(**_SEQUENCE_PORT_TYPE.reference()),
    ExactContractReference(**PROTEIN_PROMPT_PORT_TYPE.reference()),
}


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

    def __post_init__(self) -> None:
        if type(self.source) not in {
            CandidateDataReference,
            ExactPortValueReference,
        }:
            raise TypeError(
                "source must be an exact Candidate or input Port value reference"
            )
        if (
            type(self.source) is CandidateDataReference
            and self.source.data_type_id != "protein.sequence"
        ) or (
            type(self.source) is ExactPortValueReference
            and self.source.port_type not in _ALLOWED_SCALAR_SOURCES
        ):
            raise TypeError(
                "prediction residue axis source must identify an exact "
                "protein.sequence or protein.prompt Port value"
            )
        validate_residue_layout(self.layout, subject="prediction residue layout")
        validate_protein_sequence(
            self.sequence,
            subject="prediction residue sequence",
        )
        if (
            self.sequence.residue_ids is None
            or tuple(self.sequence.residue_ids)
            != tuple(self.layout.residue_ids or ())
        ):
            raise ValueError(
                "prediction sequence residue identities must exactly equal "
                "the prediction residue layout"
            )


def _finite_metric_value(
    value: object,
    *,
    field_name: str,
    minimum: float,
    maximum: float,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not minimum <= float(value) <= maximum
        or float(value) == 0.0
        and math.copysign(1.0, float(value)) < 0
    ):
        raise ValueError(
            f"{field_name} must be a finite value in [{minimum}, {maximum}]"
        )
    return float(value)


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
        if (
            type(self.prediction_key) is not str
            or _PREDICTION_KEY.fullmatch(self.prediction_key) is None
        ):
            raise ValueError(
                "prediction_key must be prediction- followed by 64 lowercase "
                "hexadecimal characters"
            )
        _require_content_digest(
            self.structure_content_digest,
            field_name="structure_content_digest",
        )
        if type(self.prediction_axis) is not PredictionResidueAxis:
            raise TypeError("prediction_axis must be a PredictionResidueAxis")
        raw_plddt = self.plddt_per_residue
        if type(raw_plddt) not in {list, tuple}:
            raise TypeError("plddt_per_residue must be an ordered value series")
        plddt = tuple(
            None
            if value is None
            else _finite_metric_value(
                value,
                field_name="plddt_per_residue",
                minimum=0.0,
                maximum=100.0,
            )
            for value in raw_plddt
        )
        if len(plddt) != self.prediction_axis.layout.length:
            raise ValueError(
                "plddt_per_residue length must exactly equal prediction axis length"
            )
        if all(value is None for value in plddt):
            raise ValueError(
                "plddt_per_residue must contain at least one non-null value"
            )
        object.__setattr__(self, "plddt_per_residue", plddt)

        if self.ptm is not None:
            object.__setattr__(
                self,
                "ptm",
                _finite_metric_value(
                    self.ptm,
                    field_name="ptm",
                    minimum=0.0,
                    maximum=1.0,
                ),
            )

        if self.pae is None:
            return
        raw_pae = self.pae
        if type(raw_pae) not in {list, tuple}:
            raise TypeError("pae must be an ordered residue-pair matrix")
        expected_length = self.prediction_axis.layout.length
        rows: list[tuple[float, ...]] = []
        for row in raw_pae:
            if type(row) not in {list, tuple} or len(row) != expected_length:
                raise ValueError(
                    "pae must be square on the exact prediction axis"
                )
            rows.append(
                tuple(
                    _finite_metric_value(
                        value,
                        field_name="pae",
                        minimum=0.0,
                        maximum=31.75,
                    )
                    for value in row
                )
            )
        if len(rows) != expected_length:
            raise ValueError("pae must be square on the exact prediction axis")
        object.__setattr__(self, "pae", tuple(rows))


@dataclass(frozen=True, slots=True)
class ConfidenceFactCollection:
    """Canonical facts produced by one exact observation Method."""

    observation_method: ExactContractReference
    entries: tuple[ConfidenceFact, ...]

    def __post_init__(self) -> None:
        method = self.observation_method
        if (
            type(method) is not ExactContractReference
            or method.contract_kind != "method"
        ):
            raise TypeError(
                "observation_method must be one exact Method reference"
            )
        validate_canonical_identifier(method.contract_id, "Method contract_id")
        if (
            type(method.contract_version) is not str
            or _SEMANTIC_VERSION.fullmatch(method.contract_version) is None
        ):
            raise ValueError(
                "observation Method contract_version must be semantic"
            )
        _require_content_digest(
            method.contract_digest,
            field_name="observation Method contract_digest",
        )

        raw_entries = self.entries
        if type(raw_entries) not in {list, tuple} or not raw_entries:
            raise ValueError(
                "ConfidenceFactCollection entries must be a nonempty ordered "
                "collection"
            )
        if any(type(entry) is not ConfidenceFact for entry in raw_entries):
            raise TypeError(
                "ConfidenceFactCollection entries must be ConfidenceFact values"
            )
        keys = tuple(entry.prediction_key for entry in raw_entries)
        if len(keys) != len(set(keys)):
            raise ValueError(
                "ConfidenceFactCollection contains a duplicate prediction_key"
            )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(raw_entries, key=lambda entry: entry.prediction_key)),
        )
