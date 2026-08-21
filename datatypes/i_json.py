"""Immutable in-memory projection for canonical I-JSON values."""

from __future__ import annotations

from collections.abc import Mapping
import math
from types import MappingProxyType
from typing import Any


_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991


class FrozenList(tuple):
    """Immutable sequence retaining JSON-array rather than tuple semantics."""

    __slots__ = ()


def freeze_i_json(value: Any, *, path: str = "$") -> Any:
    """Validate I-JSON and copy arrays/objects into immutable containers."""
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise ValueError(f"{path} is not valid Unicode I-JSON") from error
        return value
    if isinstance(value, int):
        if not -_I_JSON_INTEGER_LIMIT <= value <= _I_JSON_INTEGER_LIMIT:
            raise ValueError(f"{path} is outside the I-JSON integer domain")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} is not a finite I-JSON number")
        if value == 0.0 and math.copysign(1.0, value) < 0:
            raise ValueError(f"{path} is negative zero, not canonical I-JSON")
        return value
    if isinstance(value, Mapping):
        for key in value:
            if type(key) is not str:
                raise ValueError(f"{path} contains a non-string object key")
        return MappingProxyType(
            {
                key: freeze_i_json(item, path=f"{path}.{key}")
                for key, item in value.items()
            }
        )
    if isinstance(value, FrozenList):
        return FrozenList(
            freeze_i_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, list):
        return FrozenList(
            freeze_i_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, tuple):
        return FrozenList(
            freeze_i_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(
        f"{path} contains {type(value).__name__}, which is not I-JSON"
    )


def thaw_i_json(value: Any) -> Any:
    """Project immutable JSON containers back to ordinary JSON values."""
    if isinstance(value, Mapping):
        return {key: thaw_i_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_i_json(item) for item in value]
    return value


def i_json_values_equal(left: object, right: object) -> bool:
    """Compare admitted I-JSON values without conflating JSON scalar types."""
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            i_json_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, FrozenList) and isinstance(right, FrozenList):
        return len(left) == len(right) and all(
            i_json_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right
