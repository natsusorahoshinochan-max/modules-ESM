"""Canonical nullable residue elements shared by scientific value owners.

These checks admit elements only. Their callers own the containing value's
layout, subject, and missing-value semantics. No source normalization or
Provider-specific projection belongs here.
"""

from __future__ import annotations

from collections.abc import Sequence
import math

from datatypes.structure import NamedAtomCoordinates


AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO")
CANONICAL_SS8 = frozenset("HBEGITSC")

ABSOLUTE_SASA_QUANTITY_CONTRACT = {
    "quantity": "solvent_accessible_surface_area",
    "measure": "absolute",
    "unit": "angstrom_squared",
    "granularity": "per_residue",
    "normalization": "none",
}


def validate_sequence_elements(
    values: Sequence[object],
    *,
    subject: str,
) -> None:
    """Admit nullable single-letter amino-acid assignments."""
    for index, item in enumerate(values):
        if item is None:
            continue
        if type(item) is not str or len(item) != 1 or item not in AMINO_ACIDS:
            raise ValueError(f"{subject}[{index}] must be one amino-acid code")


def validate_coordinate_elements(
    values: Sequence[object],
    *,
    subject: str,
) -> None:
    """Admit nullable named-atom coordinates independent of Provider vocabulary."""
    for index, item in enumerate(values):
        if item is not None and type(item) is not NamedAtomCoordinates:
            raise ValueError(f"{subject}[{index}] must be NamedAtomCoordinates")


def validate_secondary_structure_elements(
    values: Sequence[object],
    *,
    subject: str,
) -> None:
    """Admit nullable canonical SS8 states, without source-token normalization."""
    for index, item in enumerate(values):
        if item is None:
            continue
        if type(item) is not str or item not in CANONICAL_SS8:
            raise ValueError(f"{subject}[{index}] must be one canonical SS8 state")


def validate_sasa_elements(
    values: Sequence[object],
    *,
    subject: str,
) -> None:
    """Admit nullable finite, non-negative absolute SASA floats in Å²."""
    for index, item in enumerate(values):
        if item is None:
            continue
        if type(item) is not float or not math.isfinite(item) or item < 0:
            raise ValueError(
                f"{subject}[{index}] must be absolute non-negative square angstroms"
            )
