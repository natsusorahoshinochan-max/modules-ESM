"""I-JSON admission, immutable representation, and canonical encoding owner."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math

import rfc8785
from types import MappingProxyType
from typing import Any


_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991


class FrozenList(tuple):
    """Immutable sequence retaining JSON-array rather than tuple semantics."""

    __slots__ = ()


def validate_i_json(value: Any, *, path: str = "$") -> None:
    """Validate the project I-JSON value domain at its owning entrance."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(f"{path} is not valid Unicode I-JSON") from error
        return
    if isinstance(value, int):
        if not -_I_JSON_INTEGER_LIMIT <= value <= _I_JSON_INTEGER_LIMIT:
            raise ValueError(f"{path} is outside the I-JSON integer domain")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} is not a finite I-JSON number")
        if value == 0.0 and math.copysign(1.0, value) < 0:
            raise ValueError(f"{path} is negative zero, not canonical I-JSON")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} contains a non-string object key")
            validate_i_json(key, path=f"{path}.<key>")
            validate_i_json(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            validate_i_json(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"{path} contains {type(value).__name__}, which is not I-JSON")


def freeze_i_json(value: Any) -> Any:
    """Copy JSON containers into an immutable representation without admission."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: freeze_i_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return FrozenList(freeze_i_json(item) for item in value)
    return value


def admit_i_json(value: Any, *, path: str = "$") -> Any:
    """Validate a raw JSON value and retain an immutable snapshot."""
    validate_i_json(value, path=path)
    return freeze_i_json(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Encode admitted JSON as RFC 8785 canonical UTF-8 bytes."""
    return rfc8785.dumps(thaw_i_json(value))


def canonical_sha256(value: Any) -> str:
    """Identify admitted JSON by its canonical bytes."""
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def thaw_i_json(value: Any) -> Any:
    """Project immutable JSON containers back to ordinary JSON values."""
    if isinstance(value, Mapping):
        return {key: thaw_i_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_i_json(item) for item in value]
    return value


def i_json_values_equal(left: object, right: object) -> bool:
    """Compare represented JSON values without conflating scalar types or zero signs."""
    if type(left) is not type(right):
        return False
    if isinstance(left, float) and left == right == 0.0:
        return math.copysign(1.0, left) == math.copysign(1.0, right)
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
