"""Contained filesystem path resolution for project and run storage."""

from __future__ import annotations

import os
import re
import stat
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


def open_private_regular_file(
    root: str | Path,
    relative_parts: tuple[str, ...],
    *,
    field: str,
) -> int:
    """Open a contained private file while holding every parent directory.

    Each path component is opened relative to the previously held directory
    descriptor. This closes the resolve/open race and rejects symlink aliases
    at every level. The returned descriptor is owned by the caller.
    """
    if not relative_parts:
        raise StoragePathError(field, f"Invalid {field}")
    absolute_root = Path(root).absolute()
    if not absolute_root.is_absolute():
        raise StoragePathError(field, f"Invalid {field}")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(absolute_root.anchor, directory_flags)
    try:
        for component in absolute_root.parts[1:]:
            next_fd = os.open(
                component,
                directory_flags,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        for component in relative_parts[:-1]:
            next_fd = os.open(
                component,
                directory_flags,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        descriptor = os.open(
            relative_parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current_fd,
        )
    except OSError:
        raise
    finally:
        os.close(current_fd)
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        os.close(descriptor)
        raise StoragePathError(field, f"Invalid {field}")
    return descriptor
