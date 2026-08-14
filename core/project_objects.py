"""Project-scoped immutable content-addressed byte storage."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re

from core.project import ProjectManager
from core.storage import (
    StoragePathError,
    fsync_private_parent_directory,
    open_private_regular_file,
    write_private_new_file,
)


_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


@dataclass(frozen=True, slots=True)
class ImmutableObject:
    """The exact identity and byte size of one durable immutable object."""

    content_digest: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "content_digest": self.content_digest,
            "size": self.size,
        }


class ObjectIntegrityError(RuntimeError):
    """A referenced immutable object no longer matches its identity."""

    def __init__(self, content_digest: str) -> None:
        self.content_digest = content_digest
        super().__init__("Immutable object failed integrity verification")


class ProjectObjectStore:
    """Own immutable bytes without knowing their domain interpretation."""

    def __init__(self, projects: ProjectManager) -> None:
        self._projects = projects

    @staticmethod
    def _relative_parts(content_digest: str) -> tuple[str, ...]:
        match = _DIGEST.fullmatch(content_digest)
        if match is None:
            raise ValueError("Object identity is not a canonical digest")
        digest = match.group(1)
        return ("v1", "sha256", digest[:2], digest[2:])

    @staticmethod
    def _read_bytes(
        root: str | Path,
        relative_parts: tuple[str, ...],
        *,
        maximum_size: int,
    ) -> bytes:
        descriptor = open_private_regular_file(
            root,
            relative_parts,
            field="immutable_object",
        )
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                payload = source.read(maximum_size + 1)
        finally:
            os.close(descriptor)
        if len(payload) > maximum_size:
            raise ValueError("Immutable object exceeds its declared size")
        return payload

    def put_exact(self, project_id: str, payload: bytes) -> ImmutableObject:
        """Durably publish exact bytes and return their content identity."""
        if type(payload) is not bytes:
            raise TypeError("Immutable object payload must be bytes")
        content_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        stored = ImmutableObject(content_digest, len(payload))
        root = self._projects.object_dir(project_id)
        parts = self._relative_parts(content_digest)
        try:
            write_private_new_file(
                root,
                parts,
                payload,
                field="immutable_object",
            )
        except FileExistsError:
            try:
                existing = self._read_bytes(
                    root,
                    parts,
                    maximum_size=stored.size,
                )
            except (OSError, StoragePathError, ValueError) as error:
                raise ObjectIntegrityError(content_digest) from error
            if existing != payload:
                raise ObjectIntegrityError(content_digest)
            fsync_private_parent_directory(
                root,
                parts,
                field="immutable_object",
            )
        return stored

    def read_exact(
        self,
        project_id: str,
        content_digest: str,
        *,
        size: int,
    ) -> bytes:
        """Read one referenced object and verify its declared identity once."""
        if type(size) is not int or size < 0:
            raise ValueError("Immutable object size is invalid")
        try:
            payload = self._read_bytes(
                self._projects.object_dir(project_id),
                self._relative_parts(content_digest),
                maximum_size=size,
            )
        except (FileNotFoundError, OSError, StoragePathError, ValueError) as error:
            raise ObjectIntegrityError(content_digest) from error
        observed_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if len(payload) != size or observed_digest != content_digest:
            raise ObjectIntegrityError(content_digest)
        return payload

    def read_bounded(
        self,
        project_id: str,
        content_digest: str,
        *,
        maximum_size: int,
    ) -> bytes:
        """Read a digest-addressed object whose exact size is in its contents."""
        if type(maximum_size) is not int or maximum_size < 0:
            raise ValueError("Immutable object read bound is invalid")
        try:
            payload = self._read_bytes(
                self._projects.object_dir(project_id),
                self._relative_parts(content_digest),
                maximum_size=maximum_size,
            )
        except (FileNotFoundError, OSError, StoragePathError, ValueError) as error:
            raise ObjectIntegrityError(content_digest) from error
        observed_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if observed_digest != content_digest:
            raise ObjectIntegrityError(content_digest)
        return payload
