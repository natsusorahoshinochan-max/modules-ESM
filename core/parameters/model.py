"""Typed results of parameter declaration and value admission."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from datatypes.i_json import freeze_i_json


@dataclass(frozen=True, slots=True)
class ParameterDeclaration:
    """One admitted scientific parameter declaration."""

    name: str
    value_contract: Mapping[str, Any]
    required: bool
    has_default: bool
    default: Any = None
    resource_kind: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "value_contract",
            freeze_i_json(self.value_contract),
        )
        if self.has_default:
            object.__setattr__(self, "default", freeze_i_json(self.default))


@dataclass(frozen=True, slots=True)
class ParameterContract:
    """Closed, admitted declarations for one exact Catalog contract."""

    entries: tuple[ParameterDeclaration, ...]
    _by_name: Mapping[str, ParameterDeclaration] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.entries, key=lambda entry: entry.name))
        by_name = {entry.name: entry for entry in ordered}
        object.__setattr__(self, "entries", ordered)
        object.__setattr__(self, "_by_name", MappingProxyType(by_name))

    def __iter__(self) -> Iterator[str]:
        return iter(self._by_name)

    def __len__(self) -> int:
        return len(self._by_name)

    def get(self, name: str) -> ParameterDeclaration | None:
        return self._by_name.get(name)

@dataclass(frozen=True, slots=True, eq=False)
class AdmittedParameterValues(Mapping[str, Any]):
    """Canonical values admitted against one exact Parameter Contract."""

    _values: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_values",
            MappingProxyType(
                {
                    name: freeze_i_json(value)
                    for name, value in sorted(self._values.items())
                }
            ),
        )

    def __getitem__(self, name: str) -> Any:
        return self._values[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)
