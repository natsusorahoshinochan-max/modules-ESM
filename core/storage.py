"""Small filesystem helpers for trusted local project storage."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import re
import tempfile


_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class StoragePathError(ValueError):
    """A storage name does not satisfy its public shape."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


def validate_identifier(value: str, field: str) -> str:
    """Return one identifier accepted by the public storage Interface."""
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise StoragePathError(field, f"Invalid {field}")
    return value


def validate_relative_path(
    value: str,
    field: str,
    *,
    allow_nested: bool = True,
) -> tuple[str, ...]:
    """Return the path parts supplied through the public Interface."""
    if not isinstance(value, str) or not value:
        raise StoragePathError(field, f"Invalid {field}")
    parts = PurePosixPath(value).parts
    if not parts or (not allow_nested and len(parts) != 1):
        raise StoragePathError(field, f"Invalid {field}")
    return parts


def contained_path(
    root: str | Path,
    *parts: str,
) -> Path:
    """Join trusted storage names beneath their configured root."""
    return Path(root).resolve().joinpath(*parts)


def _write_file(
    root: str | Path,
    relative_parts: tuple[str, ...],
    payload: bytes,
    *,
    replace: bool,
    durable: bool = False,
) -> Path:
    path = Path(root).joinpath(*relative_parts)
    missing_directories: list[Path] = []
    if durable:
        existing_ancestor = path.parent
        while not existing_ancestor.exists():
            missing_directories.append(existing_ancestor)
            existing_ancestor = existing_ancestor.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace and path.exists():
        raise FileExistsError(path)
    temporary = tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    temporary_path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(payload)
            if durable:
                temporary.flush()
                os.fsync(temporary.fileno())
        if replace:
            temporary_path.replace(path)
        else:
            temporary_path.rename(path)
        if durable:
            directories = [
                path.parent,
                *(directory.parent for directory in missing_directories),
            ]
            for directory in dict.fromkeys(directories):
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return path


def write_new_file(
    root: str | Path,
    relative_parts: tuple[str, ...],
    payload: bytes,
) -> Path:
    """Publish a new file without exposing a partial payload."""
    return _write_file(root, relative_parts, payload, replace=False)


def write_new_file_durable(
    root: str | Path,
    relative_parts: tuple[str, ...],
    payload: bytes,
) -> Path:
    """Publish and durably acknowledge one new file and its path entries."""
    return _write_file(
        root,
        relative_parts,
        payload,
        replace=False,
        durable=True,
    )


def replace_file(
    root: str | Path,
    relative_parts: tuple[str, ...],
    payload: bytes,
) -> Path:
    """Replace a rebuildable file without exposing a partial payload."""
    return _write_file(root, relative_parts, payload, replace=True)
