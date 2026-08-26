"""Shared private credential-file hygiene."""

from __future__ import annotations

import os
from pathlib import Path
import stat


_MAX_PRIVATE_CREDENTIAL_BYTES = 16 * 1024
_STABLE_CREDENTIAL_STAT_FIELDS = (
    "st_dev",
    "st_ino",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_nlink",
)


def _open_private_credential_file(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise FileNotFoundError("credential file is unavailable") from error
    file_stat = os.fstat(descriptor)
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.getuid()
        or file_stat.st_nlink != 1
        or stat.S_IMODE(file_stat.st_mode) & 0o077
        or not 0 < file_stat.st_size <= _MAX_PRIVATE_CREDENTIAL_BYTES
    ):
        os.close(descriptor)
        raise PermissionError("credential file is not private")
    return descriptor


def read_private_credential_file(path: str | Path) -> str:
    """Read one private credential through a single stable descriptor."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise FileNotFoundError("credential file path must be absolute")
    descriptor = _open_private_credential_file(candidate)
    try:
        before = os.fstat(descriptor)
        payload = os.read(descriptor, _MAX_PRIVATE_CREDENTIAL_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if any(
        getattr(before, field_name) != getattr(after, field_name)
        for field_name in _STABLE_CREDENTIAL_STAT_FIELDS
    ) or len(payload) > _MAX_PRIVATE_CREDENTIAL_BYTES:
        raise PermissionError("credential file is not private")
    token = payload.decode().strip()
    if not token:
        raise ValueError("credential file is empty")
    return token
