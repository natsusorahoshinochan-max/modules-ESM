"""Stream actual files into host-owned packages before exposing their records."""
from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
from uuid import uuid4

from protein_workbench_public.module_api import Delivery


def _error(message):
    from .application import HostError
    return HostError(message)


def _relative(value, description):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _error(f"Invalid {description}: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise _error(f"Invalid {description}, must stay within workdir: {value!r}")
    return path.parts


def receive(project_id, delivery, workdir, destination):
    if not isinstance(delivery, Delivery) or not isinstance(delivery.format, str) or not delivery.format:
        raise _error("Invalid Delivery: a nonempty format name is required")
    if not isinstance(delivery.files, Mapping) or not delivery.files:
        raise _error("Invalid Delivery: declared files must be a nonempty mapping")
    entries = list(delivery.files.items())
    keys = [key for key, _ in entries]
    if len(set(keys)) != len(keys):
        raise _error("Invalid Delivery: duplicate file keys")
    for key in keys:
        _relative(key, "file key")
    if delivery.entry not in keys:
        raise _error(f"Delivery entry {delivery.entry!r} is absent from declared files")
    package_id = uuid4().hex
    staging = destination / (".receiving-" + package_id)
    final = destination / package_id
    staging.mkdir()
    try:
        for number, (key, source) in enumerate(entries):
            parts = _relative(source, "file source")
            directory_fd = os.open(workdir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            file_fd = None
            try:
                for part in parts[:-1]:
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    os.close(directory_fd)
                    directory_fd = next_fd
                file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                info = os.fstat(file_fd)
                if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444:
                    raise _error(f"Declared file {key!r} is not a readable regular file")
                with os.fdopen(file_fd, "rb") as reader:
                    file_fd = None
                    with (staging / str(number)).open("wb") as writer:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
                        writer.flush()
                        os.fsync(writer.fileno())
            except OSError as exc:
                raise _error(f"Could not receive declared file {key!r} from {source!r}: {exc}") from exc
            finally:
                if file_fd is not None:
                    os.close(file_fd)
                os.close(directory_fd)
        os.replace(staging, final)
        return {"id": package_id, "project_id": project_id, "format": delivery.format, "entry": delivery.entry, "files": keys}
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(final, ignore_errors=True)
        raise


class StoredPackage:
    def __init__(self, record, directory):
        self._record = record
        self._directory = directory
        self.id = record["id"]
        self.format = record["format"]
        self.entry = record["entry"]
        self.files = tuple(record["files"])

    def metadata(self):
        return dict(self._record, files=list(self.files))

    def open(self, key):
        try:
            number = self.files.index(key)
        except ValueError as exc:
            raise _error(f"File {key!r} is not declared by package {self.id}") from exc
        try:
            return (self._directory / str(number)).open("rb")
        except OSError as exc:
            raise _error(f"Could not read package {self.id} file {key!r}: {exc}") from exc
