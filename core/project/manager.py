"""Project-scoped storage primitives for the sole supported v2 runtime."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core.project.storage import (
    StoragePathError,
    replace_file,
    validate_identifier,
    write_new_file,
)

CANONICAL_3GB1_PROJECT_ID = "canonical-3gb1"
MAX_PROJECT_INPUT_BYTES = 64 * 1024 * 1024
PROJECT_SCHEMA_VERSION = "2.1.0"
PROJECT_INPUT_SCHEMA_VERSION = "2.1.0"
_PROJECT_INPUT_ARTIFACT_KIND = "project_input"
_CANONICAL_STAGING_PREFIX = ".canonical-3gb1-staging-"


class CanonicalSeedError(RuntimeError):
    """The shipped canonical project cannot be safely installed."""


class ProtectedProjectError(PermissionError):
    """An ordinary write targeted the protected canonical project."""


@dataclass(frozen=True, slots=True)
class ProjectMeta:
    """Closed v2 metadata for one Project scope."""

    id: str
    name: str
    created_at: str = ""
    modified_at: str = ""
    seed: bool = False

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            object.__setattr__(self, "created_at", now)
        if not self.modified_at:
            object.__setattr__(self, "modified_at", now)


@dataclass(frozen=True, slots=True)
class ProjectInputDescriptor:
    """Typed identity for one admitted immutable Project Input."""

    project_input_ref: str
    filename: str
    size: int
    content_digest: str


class ProjectManager:
    """Own Project identity, metadata, inputs, and storage scopes."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        cache_root: str | Path | None = None,
        output_root: str | Path | None = None,
        run_root: str | Path | None = None,
    ) -> None:
        self._root_dir = Path(root_dir)
        self._cache_root = (
            Path(cache_root) if cache_root is not None else None
        )
        self._output_root = (
            Path(output_root) if output_root is not None else None
        )
        self._run_root = Path(run_root) if run_root is not None else None

    def _project_storage_root(self, project_id: str) -> Path:
        safe_project_id = validate_identifier(project_id, "project_id")
        return self._root_dir / safe_project_id

    @staticmethod
    def _validate_input_filename(filename: str) -> str:
        if type(filename) is not str or not 1 <= len(filename) <= 512:
            raise ValueError("Project input filename is invalid")
        try:
            filename.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("Project input filename is invalid") from error
        return filename

    @staticmethod
    def _input_descriptor_data(
        descriptor: ProjectInputDescriptor,
    ) -> dict[str, Any]:
        return {
            "schema_version": PROJECT_INPUT_SCHEMA_VERSION,
            "artifact_kind": _PROJECT_INPUT_ARTIFACT_KIND,
            "project_input_ref": descriptor.project_input_ref,
            "filename": descriptor.filename,
            "size": descriptor.size,
            "content_digest": descriptor.content_digest,
        }

    @classmethod
    def _input_descriptor_bytes(
        cls,
        descriptor: ProjectInputDescriptor,
    ) -> bytes:
        return json.dumps(
            cls._input_descriptor_data(descriptor),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")

    @classmethod
    def _input_descriptor(
        cls,
        input_reference: str,
        payload: bytes,
        *,
        filename: str,
    ) -> ProjectInputDescriptor:
        if len(payload) > MAX_PROJECT_INPUT_BYTES:
            raise ValueError("Project input payload is invalid or too large")
        safe_filename = cls._validate_input_filename(filename)
        return ProjectInputDescriptor(
            project_input_ref=input_reference,
            filename=safe_filename,
            size=len(payload),
            content_digest="sha256:" + hashlib.sha256(payload).hexdigest(),
        )

    def _publish_input_snapshot(
        self,
        project_dir: Path,
        input_reference: str,
        payload: bytes,
        *,
        filename: str,
    ) -> ProjectInputDescriptor:
        descriptor = self._input_descriptor(
            input_reference,
            payload,
            filename=filename,
        )
        inputs_dir = project_dir / "inputs"
        inputs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = inputs_dir / input_reference
        if destination.exists():
            raise FileExistsError(input_reference)
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{input_reference}.",
                suffix=".pending",
                dir=inputs_dir,
            )
        )
        try:
            write_new_file(
                staging_dir,
                ("descriptor.json",),
                self._input_descriptor_bytes(descriptor),
            )
            write_new_file(
                staging_dir,
                ("payload",),
                payload,
            )
            staging_dir.rename(destination)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
        return descriptor

    def publish_input(
        self,
        project_id: str,
        input_reference: str,
        payload: bytes,
        *,
        filename: str,
    ) -> ProjectInputDescriptor:
        """Atomically publish one immutable Project Input snapshot."""
        self.assert_writable(project_id)
        safe_reference = validate_identifier(
            input_reference,
            "project_input_ref",
        )
        return self._publish_input_snapshot(
            self._project_storage_root(project_id),
            safe_reference,
            payload,
            filename=filename,
        )

    def read_input(
        self,
        project_id: str,
        input_reference: str,
    ) -> tuple[ProjectInputDescriptor, bytes]:
        """Read one admitted immutable Project Input snapshot."""
        safe_reference = validate_identifier(
            input_reference,
            "project_input_ref",
        )
        input_dir = (
            self._project_storage_root(project_id) / "inputs" / safe_reference
        )
        raw = json.loads(
            (input_dir / "descriptor.json").read_text(encoding="utf-8")
        )
        if (
            not isinstance(raw, dict)
            or set(raw) != {
                "schema_version",
                "artifact_kind",
                "project_input_ref",
                "filename",
                "size",
                "content_digest",
            }
            or raw["schema_version"] != PROJECT_INPUT_SCHEMA_VERSION
            or raw["artifact_kind"] != _PROJECT_INPUT_ARTIFACT_KIND
            or raw["project_input_ref"] != safe_reference
            or type(raw["size"]) is not int
            or not 0 <= raw["size"] <= MAX_PROJECT_INPUT_BYTES
            or not isinstance(raw["content_digest"], str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", raw["content_digest"])
            is None
        ):
            raise ValueError("Project input descriptor is invalid")
        descriptor = ProjectInputDescriptor(
            project_input_ref=safe_reference,
            filename=self._validate_input_filename(raw["filename"]),
            size=raw["size"],
            content_digest=raw["content_digest"],
        )
        payload_path = input_dir / "payload"
        payload = payload_path.read_bytes()
        if (
            len(payload) != descriptor.size
            or "sha256:" + hashlib.sha256(payload).hexdigest()
            != descriptor.content_digest
        ):
            raise ValueError("Project input content identity is invalid")
        return descriptor, payload

    def result_cache_storage_root(self, project_id: str) -> Path:
        """Return the Project scope assigned to the Result replay owner."""
        if self._cache_root is None:
            return self._project_storage_root(project_id) / "cache"
        return self._cache_root / validate_identifier(project_id, "project_id")

    def _result_storage_root(self, project_id: str) -> Path:
        if self._output_root is None:
            return self._project_storage_root(project_id) / "outputs"
        return self._output_root / validate_identifier(project_id, "project_id")

    def _object_storage_root(self, project_id: str) -> Path:
        return self._result_storage_root(project_id) / "objects"

    def workflow_storage_root(self, project_id: str) -> Path:
        """Return the Project scope assigned to Workflow Authoring."""
        return self._project_storage_root(project_id) / "workflow-v2"

    def run_storage_root(self, project_id: str) -> Path:
        """Return the Project scope assigned to Run Runtime."""
        if self._run_root is None:
            return self._project_storage_root(project_id) / "runs"
        return self._run_root / validate_identifier(project_id, "project_id")

    def run_storage_directory(self, project_id: str, run_id: str) -> Path:
        """Return one exact Run Runtime storage scope."""
        safe_run_id = validate_identifier(run_id, "run_id")
        return self.run_storage_root(project_id) / safe_run_id

    def stored_run_ids(self, project_id: str) -> tuple[str, ...]:
        """List exact Run identities in the Project's Runtime scope."""
        run_root = self.run_storage_root(project_id)
        if not run_root.is_dir():
            return ()
        stored: list[str] = []
        for path in sorted(run_root.iterdir()):
            if not path.is_dir():
                continue
            stored.append(validate_identifier(path.name, "run_id"))
        return tuple(stored)

    def stored_project_ids(self) -> tuple[str, ...]:
        """List contained Project IDs that currently have local storage."""
        if not self._root_dir.is_dir():
            return ()
        stored: list[str] = []
        for path in sorted(self._root_dir.iterdir()):
            if not path.is_dir() or path.name.startswith(
                _CANONICAL_STAGING_PREFIX
            ):
                continue
            stored.append(validate_identifier(path.name, "project_id"))
        return tuple(stored)

    def _ensure_dir(self, project_id: str) -> Path:
        d = self._project_storage_root(project_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "inputs").mkdir(exist_ok=True)
        (d / "outputs").mkdir(exist_ok=True)
        return d

    # ── create ────────────────────────────────────────────────────────

    def create(self, name: str) -> ProjectMeta:
        """Create one empty v2 Project scope."""
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            raise ValueError("Project name is invalid")
        project_id = str(uuid.uuid4())
        meta = ProjectMeta(id=project_id, name=name)
        self._ensure_dir(project_id)
        self._save_meta(meta)
        return meta

    def assert_writable(self, project_id: str) -> None:
        """Reject ordinary content or metadata writes to the canonical ID."""
        if project_id == CANONICAL_3GB1_PROJECT_ID:
            raise ProtectedProjectError(
                "The canonical 3GB1 project is read-only"
            )

    def ensure_seed_project_v2(
        self,
        *,
        input_sources: Mapping[str, str | Path],
        name: str = "3GB1 Design Pipeline",
    ) -> ProjectMeta | None:
        """Install only the maintained seed Project scope and exact inputs.

        Workflow Draft and Commit state belongs exclusively to the authoring
        owner and is installed separately after the Catalog is frozen.
        """

        project_dir = self._project_storage_root(CANONICAL_3GB1_PROJECT_ID)
        metadata_path = project_dir / "project.json"
        if project_dir.exists():
            if (
                not project_dir.is_dir()
                or not metadata_path.exists()
            ):
                return None
            try:
                meta = self.load_meta(CANONICAL_3GB1_PROJECT_ID)
            except ValueError:
                # Cutover never rewrites, migrates, archives, or deletes old
                # Project state. Public reads reject it as unsupported.
                return None
            if meta is None or not meta.seed:
                return None
            return meta

        input_payloads: dict[str, tuple[str, bytes]] = {}
        for reference, source_value in input_sources.items():
            safe_reference = validate_identifier(
                reference,
                "canonical_v2_input",
            )
            source = Path(source_value)
            if not source.is_file():
                raise CanonicalSeedError(
                    f"Canonical v2 input source is unavailable: {reference}"
                )
            try:
                input_payloads[safe_reference] = (
                    source.name,
                    source.read_bytes(),
                )
            except OSError as error:
                raise CanonicalSeedError(
                    f"Canonical v2 input cannot be installed: {reference}"
                ) from error

        meta = ProjectMeta(
            id=CANONICAL_3GB1_PROJECT_ID,
            name=name,
            seed=True,
        )
        self._root_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=_CANONICAL_STAGING_PREFIX,
                dir=self._root_dir,
            )
        ).resolve()
        try:
            (staging_dir / "inputs").mkdir(mode=0o700)
            write_new_file(
                staging_dir,
                ("project.json",),
                json.dumps(
                    self._meta_data(meta),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                ).encode("utf-8"),
            )
            for reference, (filename, payload) in input_payloads.items():
                self._publish_input_snapshot(
                    staging_dir,
                    reference,
                    payload,
                    filename=filename,
                )
            if project_dir.exists():
                return None
            staging_dir.rename(project_dir)
        except (OSError, StoragePathError, ValueError) as error:
            raise CanonicalSeedError(
                "Canonical v2 Project cannot be installed safely"
            ) from error
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
        return meta

    def load_meta(self, project_id: str) -> ProjectMeta | None:
        """Load exactly one closed v2 Project metadata document."""
        path = self._project_storage_root(project_id) / "project.json"
        if not path.exists():
            return None
        if not path.is_file():
            raise StoragePathError("project_id", "Invalid Project metadata")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("unsupported Project schema version") from error
        if (
            not isinstance(raw, dict)
            or set(raw)
            != {
                "schema_version",
                "id",
                "name",
                "created_at",
                "modified_at",
                "seed",
            }
            or raw["schema_version"] != PROJECT_SCHEMA_VERSION
            or raw["id"] != project_id
            or not isinstance(raw["name"], str)
            or not isinstance(raw["created_at"], str)
            or not isinstance(raw["modified_at"], str)
            or type(raw["seed"]) is not bool
        ):
            raise ValueError("unsupported Project schema version")
        return ProjectMeta(
            id=raw["id"],
            name=raw["name"],
            created_at=raw["created_at"],
            modified_at=raw["modified_at"],
            seed=raw["seed"],
        )

    @staticmethod
    def _meta_data(meta: ProjectMeta) -> dict[str, Any]:
        return {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "id": meta.id,
            "name": meta.name,
            "created_at": meta.created_at,
            "modified_at": meta.modified_at,
            "seed": meta.seed,
        }

    def _save_meta(self, meta: ProjectMeta) -> None:
        project_dir = self._ensure_dir(meta.id)
        payload = json.dumps(
            self._meta_data(meta),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        replace_file(
            project_dir,
            ("project.json",),
            payload,
        )

    # ── seed project ──────────────────────────────────────────────────
