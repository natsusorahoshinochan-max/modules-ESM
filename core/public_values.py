"""Secret redaction for values crossing the public v2 protocol."""

from __future__ import annotations

import re
import math
from typing import Any


_SENSITIVE_KEY = re.compile(
    r"(?:secret|token|password|credential|api[_-]?key|authorization|cookie|"
    r"private[_-]?key|access[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret|authorization)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_HEADER_VALUE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)"
    r"(\s*[:=]\s*)[^\r\n]+"
)
_BASIC_VALUE = re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/=]{8,}")
_URI_USERINFO = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@")
_OPAQUE_API_TOKEN = re.compile(
    r"\b(?:"
    r"(?:sk|pk)-[A-Za-z0-9_-]{8,}|"
    r"hf_[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}"
    r")\b"
)


def _secret_values(value: Any, *, sensitive: bool = False) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            values.update(
                _secret_values(
                    child,
                    sensitive=sensitive or bool(_SENSITIVE_KEY.search(str(key))),
                )
            )
    elif isinstance(value, (list, tuple)):
        for child in value:
            values.update(_secret_values(child, sensitive=sensitive))
    elif sensitive and isinstance(value, str) and len(value) >= 4:
        values.add(value)
    return values


def _redact(value: Any, secret_values: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else _redact(child, secret_values)
            )
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(child, secret_values) for child in value]
    if not isinstance(value, str):
        return value
    redacted = value
    for secret in secret_values:
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _HEADER_VALUE.sub(r"\1\2[REDACTED]", redacted)
    redacted = _BEARER_VALUE.sub(r"\1[REDACTED]", redacted)
    redacted = _BASIC_VALUE.sub("Basic [REDACTED]", redacted)
    redacted = _KEY_VALUE.sub(r"\1\2[REDACTED]", redacted)
    redacted = _URI_USERINFO.sub(r"\1[REDACTED]@", redacted)
    return _OPAQUE_API_TOKEN.sub("[REDACTED]", redacted)


def sanitize_public_value(value: Any) -> Any:
    """Return a recursively redacted value safe for public API responses."""
    secret_values = tuple(
        sorted(_secret_values(value), key=len, reverse=True)
    )
    return _redact(value, secret_values)


def validate_public_scientific_value(
    value: Any,
    *,
    depth: int = 0,
) -> None:
    """Accept only bounded, finite, already-redacted scientific JSON."""
    if depth > 12:
        raise ValueError("Scientific value nesting is too deep")
    if isinstance(value, dict):
        if len(value) > 128:
            raise ValueError("Scientific object is too large")
        for key, child in value.items():
            if (
                not isinstance(key, str)
                or len(key) > 128
                or sanitize_public_value(key) != key
            ):
                raise ValueError("Scientific object key is unsafe")
            validate_public_scientific_value(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 4096:
            raise ValueError("Scientific array is too large")
        for child in value:
            validate_public_scientific_value(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if (
        isinstance(value, str)
        and len(value) <= 512
        and sanitize_public_value(value) == value
    ):
        return
    raise ValueError("Scientific value is not safe JSON")
