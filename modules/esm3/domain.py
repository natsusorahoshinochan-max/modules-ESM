"""Package-owned scientific values produced by direct ESMC inference."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct


_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO")
ESMC_MEAN_EMBEDDING_DIMENSION = 1152
ESMC_SEQUENCE_LOGITS_DIMENSION = 64


@dataclass(frozen=True, slots=True)
class ESMCSequenceRepresentation:
    """One exact provider-returned sequence representation.

    The embedding is the Biohub ESMC mean embedding.  The logits themselves are
    intentionally not retained because their transfer and persistence cost is
    disproportionate; their exact returned tensor shape is retained.  This
    value owns the one fixed ESMC-600M representation contract admitted by the
    Workbench.
    """

    sequence: str
    residue_ids: tuple[str, ...] | None
    mean_embedding: tuple[float, ...]
    sequence_logits_shape: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            not self.sequence
            or any(symbol not in _AMINO_ACIDS for symbol in self.sequence)
        ):
            raise ValueError(
                "ESMC sequence representation requires canonical amino acids"
            )
        if self.residue_ids is not None and (
            len(self.residue_ids) != len(self.sequence)
            or any(
                type(residue_id) is not str or not residue_id
                for residue_id in self.residue_ids
            )
        ):
            raise ValueError(
                "ESMC representation residue IDs must match the sequence axis"
            )
        if (
            not self.mean_embedding
            or any(
                type(value) is not float or not math.isfinite(value)
                for value in self.mean_embedding
            )
        ):
            raise ValueError(
                "ESMC mean embedding must contain finite binary32 values"
            )
        if len(self.mean_embedding) != ESMC_MEAN_EMBEDDING_DIMENSION:
            raise ValueError("ESMC mean embedding must contain 1152 values")
        if any(
            value == 0.0 and math.copysign(1.0, value) < 0.0
            for value in self.mean_embedding
        ):
            raise ValueError(
                "ESMC mean embedding cannot contain negative zero"
            )
        try:
            binary32_round_trips = all(
                struct.unpack(">f", struct.pack(">f", value))[0] == value
                for value in self.mean_embedding
            )
        except (OverflowError, struct.error):
            binary32_round_trips = False
        if not binary32_round_trips:
            raise ValueError(
                "ESMC mean embedding values must be exactly representable "
                "as binary32"
            )
        if (
            any(type(value) is not int for value in self.sequence_logits_shape)
            or self.sequence_logits_shape
            != (
                len(self.sequence) + 2,
                ESMC_SEQUENCE_LOGITS_DIMENSION,
            )
        ):
            raise ValueError(
                "ESMC sequence logits shape must be the exact integer shape "
                "(L + 2, 64)"
            )
