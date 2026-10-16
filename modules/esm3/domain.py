"""ESMC values on the original sequence residue axis."""
from dataclasses import dataclass
import math


ESMC_MEAN_EMBEDDING_DIMENSION = 1152
ESMC_SEQUENCE_LOGITS_DIMENSION = 64


@dataclass(frozen=True, slots=True)
class ESMCSequenceRepresentation:
    """Optional provider values; logits retain all 64 model classes, not probabilities."""
    sequence: str
    residue_ids: tuple[str, ...] | None
    mean_embedding: tuple[float, ...] | None
    sequence_logits: tuple[tuple[float, ...], ...] | None

    def __post_init__(self) -> None:
        if not self.sequence:
            raise ValueError("ESMC representation requires a sequence")
        if self.residue_ids is not None and len(self.residue_ids) != len(self.sequence):
            raise ValueError("ESMC residue IDs must match the sequence axis")
        if self.mean_embedding is None and self.sequence_logits is None:
            raise ValueError("ESMC representation requires a requested output")
        if self.mean_embedding is not None:
            if (
                len(self.mean_embedding) != ESMC_MEAN_EMBEDDING_DIMENSION
                or not all(math.isfinite(v) for v in self.mean_embedding)
            ):
                raise ValueError("ESMC mean embedding requires 1152 finite values")
        if self.sequence_logits is not None:
            if len(self.sequence_logits) != len(self.sequence) or any(
                len(row) != ESMC_SEQUENCE_LOGITS_DIMENSION
                or not all(math.isfinite(v) for v in row)
                for row in self.sequence_logits
            ):
                raise ValueError("ESMC logits require one row of 64 finite values per residue")
