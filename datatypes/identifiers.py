"""Canonical identifiers shared by public scientific values."""

from __future__ import annotations

import re


_CANONICAL_IDENTIFIER = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$"
)


def validate_canonical_identifier(
    value: object,
    field_name: str = "identifier",
) -> str:
    """Return one exact public Identifier or raise ``ValueError``.

    The contract deliberately requires an exact ``str`` rather than accepting
    subclasses or coercing another value into text.
    """
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or _CANONICAL_IDENTIFIER.fullmatch(value) is None
    ):
        raise ValueError(f"{field_name} must be a canonical identifier")
    return value


__all__ = ["validate_canonical_identifier"]
