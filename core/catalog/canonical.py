"""Canonical I-JSON bytes and content digests."""

from collections.abc import Mapping
import hashlib
import math
from types import MappingProxyType
from typing import Any

import rfc8785

from core.catalog.errors import CatalogBuildError as _BuildError
from datatypes.i_json import FrozenList, thaw_i_json


_I_JSON_INTEGER_LIMIT = 9_007_199_254_740_991


def _validate(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise _BuildError(
                    f"{path} contains a non-Unicode scalar value"
                ) from error
        return
    if isinstance(value, int):
        if not -_I_JSON_INTEGER_LIMIT <= value <= _I_JSON_INTEGER_LIMIT:
            raise _BuildError(f"{path} is outside the I-JSON integer domain")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _BuildError(f"{path} must not contain NaN or Infinity")
        if value == 0.0 and math.copysign(1.0, value) < 0:
            raise _BuildError(f"{path} must not contain negative zero")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _BuildError(f"{path} has a non-string object key")
            _validate(key, path=f"{path}.<key>")
            _validate(item, path=f"{path}.{key}")
        return
    raise _BuildError(
        f"{path} contains a value that cannot be represented in I-JSON"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return RFC 8785 canonical UTF-8 after enforcing Workbench I-JSON."""
    projected = thaw_i_json(value)
    _validate(projected)
    try:
        return rfc8785.dumps(projected)
    except (rfc8785.CanonicalizationError, UnicodeError) as error:
        raise _BuildError("value cannot be canonicalized with RFC 8785") from error


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return FrozenList(_freeze(item) for item in value)
    return value


def canonical_sha256(value: Any) -> str:
    """Return the public digest of canonical I-JSON bytes."""
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"
