"""Compatibility import for the public ProteinMPNN constraints validator."""

from datatypes import (
    PROTEINMPNN_ALPHABET as ALPHABET,
    validate_proteinmpnn_constraints as validate_constraints,
)

__all__ = ["ALPHABET", "validate_constraints"]
