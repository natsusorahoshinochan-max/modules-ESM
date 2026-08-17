"""Project-scoped content-addressed scientific bytes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from core.project import ProjectManager
from core.storage import write_new_file


_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


@dataclass(frozen=True, slots=True)
class ImmutableObject:
    """The content identity and size of one admitted value."""

    content_digest: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "content_digest": self.content_digest,
            "size": self.size,
        }


class ObjectIntegrityError(RuntimeError):
    """A referenced object is unavailable."""

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

    def put_exact(self, project_id: str, payload: bytes) -> ImmutableObject:
        """Store bytes once and return their content identity."""
        content_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        stored = ImmutableObject(content_digest, len(payload))
        try:
            write_new_file(
                self._projects.object_dir(project_id),
                self._relative_parts(content_digest),
                payload,
            )
        except FileExistsError:
            pass
        return stored

    def _read(self, project_id: str, content_digest: str) -> bytes:
        path = self._projects.object_dir(project_id).joinpath(
            *self._relative_parts(content_digest)
        )
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise ObjectIntegrityError(content_digest) from error

    def read(self, project_id: str, content_digest: str) -> bytes:
        """Return bytes previously admitted by this store."""
        return self._read(project_id, content_digest)
