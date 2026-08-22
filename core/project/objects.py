"""Project-scoped content-addressed scientific bytes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from core.project.manager import ProjectManager
from core.project.storage import write_new_file


_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


@dataclass(frozen=True, slots=True)
class StoredObject:
    """The content identity and size of exact stored bytes."""

    content_digest: str
    size: int


class ObjectIntegrityError(RuntimeError):
    """A referenced object is unavailable or has changed identity."""

    def __init__(self, content_digest: str) -> None:
        self.content_digest = content_digest
        super().__init__("Immutable object is unavailable")


class ProjectObjectStore:
    """Store and retrieve bytes by their admitted content identity."""

    def __init__(self, projects: ProjectManager) -> None:
        self._projects = projects

    @staticmethod
    def _relative_parts(content_digest: str) -> tuple[str, ...]:
        match = _DIGEST.fullmatch(content_digest)
        if match is None:
            raise ValueError("Object identity is not a canonical digest")
        digest = match.group(1)
        return ("v1", "sha256", digest[:2], digest[2:])

    def store(self, project_id: str, canonical_bytes: bytes) -> StoredObject:
        """Atomically store exact bytes and return their content identity."""
        content_digest = (
            "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
        )
        stored = StoredObject(content_digest, len(canonical_bytes))
        try:
            write_new_file(
                self._projects._object_storage_root(project_id),
                self._relative_parts(content_digest),
                canonical_bytes,
            )
        except FileExistsError:
            if self.read(project_id, content_digest) != canonical_bytes:
                raise ObjectIntegrityError(content_digest)
        return stored

    def _read(self, project_id: str, content_digest: str) -> bytes:
        path = self._projects._object_storage_root(project_id).joinpath(
            *self._relative_parts(content_digest)
        )
        try:
            return path.read_bytes()
        except OSError as error:
            raise ObjectIntegrityError(content_digest) from error

    def read(self, project_id: str, content_digest: str) -> bytes:
        """Return immutable bytes matching the exact requested identity."""
        payload = self._read(project_id, content_digest)
        actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual_digest != content_digest:
            raise ObjectIntegrityError(content_digest)
        return payload
