"""Test fixture adapter for explicit resolved Catalog dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datatypes.exact_reference import ExactContractReference


_REFERENCE_FIELDS = {
    "contract_kind",
    "contract_id",
    "contract_version",
    "contract_digest",
}


def resolved_dependencies(value: Any) -> tuple[ExactContractReference, ...]:
    references: dict[tuple[str, str, str], ExactContractReference] = {}
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping) and set(current) == _REFERENCE_FIELDS:
            reference = ExactContractReference(**current)
            references[reference.key] = reference
        elif isinstance(current, Mapping):
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
    return tuple(references[key] for key in sorted(references))
