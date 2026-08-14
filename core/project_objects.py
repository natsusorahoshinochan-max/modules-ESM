"""Project-scoped immutable content-addressed byte storage."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Iterator
import uuid

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
        self._guard = threading.Lock()
        self._project_locks: dict[str, threading.RLock] = {}
        self._active_writers: dict[tuple[str, str], set[str]] = {}
        self._writer_context = threading.local()

    def _project_lock(self, project_id: str) -> threading.RLock:
        with self._guard:
            return self._project_locks.setdefault(
                project_id,
                threading.RLock(),
            )

    @contextmanager
    def active_writer(self, project_id: str) -> Iterator[None]:
        """Keep this thread's published objects live until its owner closes."""
        writer_id = f"writer-{uuid.uuid4().hex}"
        key = (project_id, writer_id)
        lock = self._project_lock(project_id)
        with lock:
            if getattr(self._writer_context, "owner", None) is not None:
                raise RuntimeError("Immutable object writer is already active")
            writer_dir = self._projects.staging_dir(project_id) / writer_id
            writer_dir.mkdir(mode=0o700, parents=True)
            self._active_writers[key] = set()
            self._writer_context.owner = key
        try:
            yield
        finally:
            with lock:
                self._writer_context.owner = None
                self._active_writers.pop(key)

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
        with self._project_lock(project_id):
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
            owner = getattr(self._writer_context, "owner", None)
            if owner is not None:
                if owner[0] != project_id:
                    raise RuntimeError(
                        "Immutable object writer belongs to another Project"
                    )
                self._active_writers[owner].add(content_digest)
        return stored

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _stale_staging_paths(self, project_id: str) -> list[Path]:
        staging_root = self._projects.staging_dir(project_id)
        if not staging_root.exists():
            return []
        if staging_root.is_symlink() or not staging_root.is_dir():
            raise StoragePathError(
                "immutable_object_staging",
                "Invalid immutable object staging namespace",
            )
        active_names = {
            writer_id
            for owner_project_id, writer_id in self._active_writers
            if owner_project_id == project_id
        }
        return [
            path
            for path in staging_root.iterdir()
            if path.name not in active_names
        ]

    def collect_unreferenced(
        self,
        project_id: str,
        referenced_digests: set[str],
    ) -> None:
        """Remove only objects lacking committed, Cache, or active ownership."""
        for content_digest in referenced_digests:
            self._relative_parts(content_digest)
        with self._project_lock(project_id):
            live = set(referenced_digests)
            for (owner_project_id, _writer_id), owned in (
                self._active_writers.items()
            ):
                if owner_project_id == project_id:
                    live.update(owned)

            object_root = self._projects.object_dir(project_id)
            digest_root = object_root / "v1" / "sha256"
            removals: list[Path] = []
            digest_directories: list[Path] = []
            if digest_root.exists():
                if digest_root.is_symlink() or not digest_root.is_dir():
                    raise StoragePathError(
                        "immutable_object",
                        "Invalid immutable object namespace",
                    )
                for prefix_dir in digest_root.iterdir():
                    if (
                        prefix_dir.is_symlink()
                        or not prefix_dir.is_dir()
                        or re.fullmatch(r"[0-9a-f]{2}", prefix_dir.name)
                        is None
                    ):
                        raise StoragePathError(
                            "immutable_object",
                            "Invalid immutable object namespace",
                        )
                    digest_directories.append(prefix_dir)
                    for candidate in prefix_dir.iterdir():
                        if candidate.is_symlink() or not candidate.is_file():
                            raise StoragePathError(
                                "immutable_object",
                                "Invalid immutable object namespace",
                            )
                        suffix_match = re.fullmatch(
                            r"[0-9a-f]{62}",
                            candidate.name,
                        )
                        if suffix_match is None:
                            if candidate.name.startswith("."):
                                removals.append(candidate)
                                continue
                            raise StoragePathError(
                                "immutable_object",
                                "Invalid immutable object namespace",
                            )
                        content_digest = (
                            f"sha256:{prefix_dir.name}{candidate.name}"
                        )
                        if content_digest not in live:
                            removals.append(candidate)

            for candidate in removals:
                parent = candidate.parent
                candidate.unlink()
                self._fsync_directory(parent)
            for prefix_dir in digest_directories:
                if next(prefix_dir.iterdir(), None) is None:
                    prefix_dir.rmdir()
                    self._fsync_directory(digest_root)

            staging_root = self._projects.staging_dir(project_id)
            for stale in self._stale_staging_paths(project_id):
                if stale.is_symlink() or stale.is_file():
                    stale.unlink()
                elif stale.is_dir():
                    shutil.rmtree(stale)
                else:
                    raise StoragePathError(
                        "immutable_object_staging",
                        "Invalid immutable object staging namespace",
                    )
                self._fsync_directory(staging_root)

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
