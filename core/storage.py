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


def _absolute_storage_root(root: str | Path, field: str) -> Path:
    absolute_root = Path(root).absolute()
    if (
        not absolute_root.is_absolute()
        or len(absolute_root.parts) < 2
        or any(
            component in {".", ".."}
            for component in absolute_root.parts[1:]
        )
    ):
        raise StoragePathError(field, f"Invalid {field}")
    return absolute_root


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
    absolute_root = _absolute_storage_root(root, field)
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


def write_private_new_file(
    root: str | Path,
    relative_parts: tuple[str, ...],
    payload: bytes,
    *,
    field: str,
) -> Path:
    """Create one private contained file without following or replacing links."""
    if not relative_parts:
        raise StoragePathError(field, f"Invalid {field}")
    absolute_root = _absolute_storage_root(root, field)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(absolute_root.anchor, directory_flags)
    descriptor: int | None = None
    created = False
    try:
        for component in absolute_root.parts[1:]:
            try:
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=current_fd)
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=current_fd,
                )
            os.close(current_fd)
            current_fd = next_fd
        root_metadata = os.fstat(current_fd)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != os.getuid()
        ):
            raise StoragePathError(field, f"Invalid {field}")
        os.fchmod(current_fd, 0o700)

        for component in relative_parts[:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(
                component,
                directory_flags,
                dir_fd=current_fd,
            )
            metadata = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
            ):
                os.close(next_fd)
                raise StoragePathError(field, f"Invalid {field}")
            os.fchmod(next_fd, 0o700)
            os.close(current_fd)
            current_fd = next_fd

        descriptor = os.open(
            relative_parts[-1],
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=current_fd,
        )
        created = True
        with os.fdopen(descriptor, "wb", closefd=False) as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise StoragePathError(field, f"Invalid {field}")
        os.fsync(current_fd)
        return absolute_root.joinpath(*relative_parts)
    except Exception:
        if created:
            try:
                os.unlink(relative_parts[-1], dir_fd=current_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(current_fd)


def remove_private_regular_file(
    root: str | Path,
    relative_parts: tuple[str, ...],
    *,
    field: str,
) -> bool:
    """Remove one contained owner-only regular file without following links."""
    if not relative_parts:
        raise StoragePathError(field, f"Invalid {field}")
    absolute_root = _absolute_storage_root(root, field)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(absolute_root.anchor, directory_flags)
    descriptor: int | None = None
    try:
        for component in (
            *absolute_root.parts[1:],
            *relative_parts[:-1],
        ):
            next_fd = os.open(
                component,
                directory_flags,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        try:
            descriptor = os.open(
                relative_parts[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current_fd,
            )
        except FileNotFoundError:
            return False
        metadata = os.fstat(descriptor)
        current = os.stat(
            relative_parts[-1],
            dir_fd=current_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or (metadata.st_dev, metadata.st_ino)
            != (current.st_dev, current.st_ino)
        ):
            raise StoragePathError(field, f"Invalid {field}")
        os.unlink(relative_parts[-1], dir_fd=current_fd)
        os.fsync(current_fd)
        return True
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(current_fd)
