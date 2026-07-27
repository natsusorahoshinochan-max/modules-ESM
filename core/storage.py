"""Contained filesystem path resolution for project and run storage."""

from __future__ import annotations

import re
from pathlib import Path
from pathlib import PurePosixPath


_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class StoragePathError(ValueError):
    """An API-controlled storage identifier or path is unsafe."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


def validate_identifier(value: str, field: str) -> str:
    """Return a safe storage identifier or raise before filesystem access."""
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise StoragePathError(field, f"Invalid {field}")
    if value in {".", ".."}:
        raise StoragePathError(field, f"Invalid {field}")
    return value


def validate_relative_path(
    value: str,
    field: str,
    *,
    allow_nested: bool = True,
) -> tuple[str, ...]:
    """Validate a portable relative path before resolving it."""
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise StoragePathError(field, f"Invalid {field}")

    path = PurePosixPath(value)
    parts = path.parts
    if (
        path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or (not allow_nested and len(parts) != 1)
    ):
        raise StoragePathError(field, f"Invalid {field}")
    return parts


def contained_path(
    root: str | Path,
    *parts: str,
    field: str = "path",
) -> Path:
    """Resolve path parts beneath root without accepting namespace aliases."""
    resolved_root = Path(root).resolve()
    candidate = resolved_root
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            raise StoragePathError(field, f"Invalid {field}")
    candidate = candidate.resolve()
    if not candidate.is_relative_to(resolved_root):
        raise StoragePathError(field, f"Invalid {field}")
    return candidate
