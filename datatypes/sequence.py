"""Provider-independent protein sequence values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from datatypes.i_json import FrozenList
from datatypes.residue import residue_identity_chain


_UPPERCASE_AMINO_ACID_ALPHABET = frozenset(
    "ACDEFGHIKLMNPQRSTVWYBXZJUO"
)


def _ordered_list(value: object, *, field_name: str) -> FrozenList:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an ordered list or tuple")
    return FrozenList(value)

@dataclass(frozen=True, slots=True)
class ProteinSequence:
    """Amino acid sequence with residue identifiers.

    sequence: one-letter amino acid codes (str, no spaces).
    residue_ids: optional list of residue labels matching sequence length.
    """

    sequence: str
    residue_ids: Optional[tuple[str, ...]] = None

    def __post_init__(self) -> None:
        if self.residue_ids is not None:
            object.__setattr__(
                self,
                "residue_ids",
                _ordered_list(self.residue_ids, field_name="residue_ids"),
            )
        if self.residue_ids is not None and len(self.residue_ids) != len(self.sequence):
            raise ValueError(
                f"residue_ids length {len(self.residue_ids)} != sequence length {len(self.sequence)}"
            )

    def __len__(self) -> int:
        return len(self.sequence)


def validate_protein_sequence(
    value: object,
    *,
    subject: str = "protein sequence",
) -> ProteinSequence:
    """Admit one exact sequence and optional canonical residue identities.

    Chain topology is owned by :class:`ResidueLayout`; a sequence therefore
    does not impose contiguous chain boundaries on its optional identities.
    """
    if type(value) is not ProteinSequence:
        raise ValueError(f"{subject} must be a ProteinSequence")
    sequence = value.sequence
    if (
        type(sequence) is not str
        or not sequence
        or any(
            character not in _UPPERCASE_AMINO_ACID_ALPHABET
            for character in sequence
        )
    ):
        raise ValueError(
            f"{subject} must use the exact uppercase amino-acid alphabet"
        )
    residue_ids = value.residue_ids
    seen_residue_ids: set[str] = set()
    for index, residue_id in enumerate(residue_ids or ()):
        residue_identity_chain(
            residue_id,
            subject=f"{subject} residue identity at index {index}",
        )
        if residue_id in seen_residue_ids:
            raise ValueError(
                f"{subject} contains duplicate residue identities"
            )
        seen_residue_ids.add(residue_id)
    return value
