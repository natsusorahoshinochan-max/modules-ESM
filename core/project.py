"""Project-scoped storage primitives for the sole supported v2 runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core.storage import (
    StoragePathError,
    contained_path,
    open_private_regular_file,
    replace_private_regular_file,
    validate_identifier,
    validate_relative_path,
    write_private_new_file,
)

CANONICAL_3GB1_PROJECT_ID = "canonical-3gb1"
MAX_PROJECT_INPUT_BYTES = 64 * 1024 * 1024
MAX_PROJECT_INPUT_DESCRIPTOR_BYTES = 8 * 1024
PROJECT_SCHEMA_VERSION = "2.1.0"
PROJECT_INPUT_SCHEMA_VERSION = "2.1.0"
_PROJECT_INPUT_ARTIFACT_KIND = "project_input"
_PROJECT_INPUT_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class CanonicalSeedError(RuntimeError):
    """The shipped canonical project cannot be safely installed."""


class ProtectedProjectError(PermissionError):
    """An ordinary write targeted the protected canonical project."""


class ProjectInputIntegrityError(ValueError):
    """One published Project Input snapshot failed durable verification."""

    def __init__(self, project_input_ref: str) -> None:
        super().__init__("Project input snapshot failed integrity verification")
        self.project_input_ref = project_input_ref


@dataclass
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
            self.created_at = now
        if not self.modified_at:
            self.modified_at = now


class ProjectManager:
    """Manage v2 Project identity, inputs, Cache, Runs, and artifacts."""

    def __init__(
        self,
        root_dir: str | Path = "projects",
        *,
        cache_root: str | Path | None = None,
        output_root: str | Path | None = None,
        run_root: str | Path | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.cache_root = Path(cache_root) if cache_root is not None else None
        self.output_root = Path(output_root) if output_root is not None else None
        self.run_root = Path(run_root) if run_root is not None else None

    def _project_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id)

    def project_dir(self, project_id: str) -> Path:
        """Resolve a project directory beneath the configured project root."""
        safe_project_id = validate_identifier(project_id, "project_id")
        return contained_path(self.root_dir, safe_project_id)

    def input_path(self, project_id: str, input_reference: str) -> Path:
        """Resolve one immutable Project Input payload for local diagnostics."""
        safe_reference = validate_identifier(
            input_reference,
            "project_input_ref",
        )
        return contained_path(
            self.project_dir(project_id),
            "inputs",
            safe_reference,
            "payload",
            field="project_input_ref",
        )

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
    def _input_descriptor_bytes(descriptor: Mapping[str, Any]) -> bytes:
        try:
            return json.dumps(
                dict(descriptor),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise ValueError("Project input descriptor is invalid") from error

    @classmethod
    def _input_descriptor(
        cls,
        input_reference: str,
        payload: bytes,
        *,
        filename: str,
    ) -> dict[str, Any]:
        if (
            type(payload) is not bytes
            or len(payload) > MAX_PROJECT_INPUT_BYTES
        ):
            raise ValueError("Project input payload is invalid or too large")
        safe_filename = cls._validate_input_filename(filename)
        return {
            "schema_version": PROJECT_INPUT_SCHEMA_VERSION,
            "artifact_kind": _PROJECT_INPUT_ARTIFACT_KIND,
            "project_input_ref": input_reference,
            "filename": safe_filename,
            "size": len(payload),
            "content_digest": (
                "sha256:" + hashlib.sha256(payload).hexdigest()
            ),
        }

    @staticmethod
    def _public_input_descriptor(
        descriptor: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "project_input_ref": descriptor["project_input_ref"],
            "filename": descriptor["filename"],
            "size": descriptor["size"],
            "content_digest": descriptor["content_digest"],
        }

    @staticmethod
    def _read_private_bytes(
        root: Path,
        relative_parts: tuple[str, ...],
        *,
        field: str,
        maximum_size: int,
    ) -> bytes:
        file_descriptor = open_private_regular_file(
            root,
            relative_parts,
            field=field,
        )
        try:
            with os.fdopen(file_descriptor, "rb", closefd=False) as source:
                payload = source.read(maximum_size + 1)
        finally:
            os.close(file_descriptor)
        if len(payload) > maximum_size:
            raise ValueError(f"{field} exceeds the supported size")
        return payload

    def _publish_input_snapshot(
        self,
        project_dir: Path,
        input_reference: str,
        payload: bytes,
        *,
        filename: str,
    ) -> dict[str, Any]:
        descriptor = self._input_descriptor(
            input_reference,
            payload,
            filename=filename,
        )
        inputs_dir = contained_path(
            project_dir,
            "inputs",
            field="project_input_ref",
        )
        inputs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = contained_path(
            inputs_dir,
            input_reference,
            field="project_input_ref",
        )
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
            write_private_new_file(
                staging_dir,
                ("descriptor.json",),
                self._input_descriptor_bytes(descriptor),
                field="project_input_descriptor",
            )
            write_private_new_file(
                staging_dir,
                ("payload",),
                payload,
                field="project_input_ref",
            )
            if destination.exists():
                raise FileExistsError(input_reference)
            staging_dir.rename(destination)
            directory_descriptor = os.open(
                inputs_dir,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
        return self._public_input_descriptor(descriptor)

    def publish_input(
        self,
        project_id: str,
        input_reference: str,
        payload: bytes,
        *,
        filename: str,
    ) -> dict[str, Any]:
        """Atomically publish one immutable Project Input snapshot."""
        self.assert_writable(project_id)
        safe_reference = validate_identifier(
            input_reference,
            "project_input_ref",
        )
        return self._publish_input_snapshot(
            self.project_dir(project_id),
            safe_reference,
            payload,
            filename=filename,
        )

    def read_input(
        self,
        project_id: str,
        input_reference: str,
    ) -> tuple[dict[str, Any], bytes]:
        """Read and verify one exact immutable Project Input snapshot."""
        safe_reference = validate_identifier(
            input_reference,
            "project_input_ref",
        )
        project_dir = self.project_dir(project_id)
        try:
            descriptor_bytes = self._read_private_bytes(
                project_dir,
                ("inputs", safe_reference, "descriptor.json"),
                field="project_input_descriptor",
                maximum_size=MAX_PROJECT_INPUT_DESCRIPTOR_BYTES,
            )
        except FileNotFoundError:
            raise
        except (OSError, StoragePathError, ValueError) as error:
            raise ProjectInputIntegrityError(safe_reference) from error
        try:
            descriptor = json.loads(descriptor_bytes.decode("utf-8"))
            if (
                not isinstance(descriptor, dict)
                or set(descriptor)
                != {
                    "schema_version",
                    "artifact_kind",
                    "project_input_ref",
                    "filename",
                    "size",
                    "content_digest",
                }
                or descriptor["schema_version"]
                != PROJECT_INPUT_SCHEMA_VERSION
                or descriptor["artifact_kind"]
                != _PROJECT_INPUT_ARTIFACT_KIND
                or descriptor["project_input_ref"] != safe_reference
                or type(descriptor["size"]) is not int
                or not 0 <= descriptor["size"] <= MAX_PROJECT_INPUT_BYTES
                or type(descriptor["content_digest"]) is not str
                or _PROJECT_INPUT_DIGEST_PATTERN.fullmatch(
                    descriptor["content_digest"]
                )
                is None
            ):
                raise ValueError("Project input descriptor is invalid")
            self._validate_input_filename(descriptor["filename"])
            if descriptor_bytes != self._input_descriptor_bytes(descriptor):
                raise ValueError("Project input descriptor is not canonical")
            payload = self._read_private_bytes(
                project_dir,
                ("inputs", safe_reference, "payload"),
                field="project_input_ref",
                maximum_size=MAX_PROJECT_INPUT_BYTES,
            )
            observed_digest = (
                "sha256:" + hashlib.sha256(payload).hexdigest()
            )
            if (
                len(payload) != descriptor["size"]
                or observed_digest != descriptor["content_digest"]
            ):
                raise ValueError(
                    "Project input payload size or digest mismatch"
                )
        except (OSError, StoragePathError, ValueError) as error:
            raise ProjectInputIntegrityError(safe_reference) from error
        return self._public_input_descriptor(descriptor), payload

    def cache_dir(self, project_id: str) -> Path:
        """Resolve the shared content-addressed Cache directory for a project."""
        if self.cache_root is None:
            return contained_path(self.project_dir(project_id), "cache")
        return contained_path(
            self.cache_root,
            validate_identifier(project_id, "project_id"),
        )

    def _output_base(self, project_id: str) -> Path:
        if self.output_root is None:
            return contained_path(self.project_dir(project_id), "outputs")
        return contained_path(
            self.output_root,
            validate_identifier(project_id, "project_id"),
        )

    def output_dir(self, project_id: str, run_id: str) -> Path:
        """Resolve one run's artifact directory."""
        safe_run_id = validate_identifier(run_id, "run_id")
        return contained_path(self._output_base(project_id), safe_run_id)

    def object_dir(self, project_id: str) -> Path:
        """Resolve one Project's shared immutable object namespace."""
        return contained_path(self._output_base(project_id), "objects")

    def staging_dir(self, project_id: str) -> Path:
        """Resolve one Project's private immutable-object writer namespace."""
        return contained_path(self._output_base(project_id), "staging")

    def run_dir(self, project_id: str, run_id: str) -> Path:
        """Resolve one run's mutable namespace."""
        safe_run_id = validate_identifier(run_id, "run_id")
        if self.run_root is None:
            base = contained_path(self.project_dir(project_id), "runs")
        else:
            base = contained_path(
                self.run_root,
                validate_identifier(project_id, "project_id"),
            )
        return contained_path(base, safe_run_id)

    def run_context(
        self,
        project_id: str,
        run_id: str,
        node_id: str,
        *,
        seed: int = 42,
    ) -> "RunContext":
        """Build a context whose mutable paths are project/run contained."""
        from core.run_context import RunContext

        safe_node_id = validate_identifier(node_id, "node_id")
        run_dir = self.run_dir(project_id, run_id)
        return RunContext(
            project_dir=str(self.project_dir(project_id)),
            node_id=safe_node_id,
            run_id=run_id,
            seed=seed,
            temp_dir=str(
                contained_path(run_dir, "temp", safe_node_id)
            ),
            output_dir=str(self.output_dir(project_id, run_id)),
            log_dir=str(contained_path(run_dir, "logs")),
        )

    def _ensure_dir(self, project_id: str) -> Path:
        d = self._project_dir(project_id)
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
        safe_project_id = validate_identifier(project_id, "project_id")
        if safe_project_id == CANONICAL_3GB1_PROJECT_ID:
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

        project_dir = self.project_dir(CANONICAL_3GB1_PROJECT_ID)
        metadata_path = project_dir / "project.json"
        if project_dir.exists():
            if (
                project_dir.is_symlink()
                or not project_dir.is_dir()
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
            reference_parts = validate_relative_path(
                reference,
                "canonical_v2_input",
                allow_nested=False,
            )
            source = Path(source_value)
            if not source.is_file() or source.is_symlink():
                raise CanonicalSeedError(
                    f"Canonical v2 input source is unavailable: {reference}"
                )
            try:
                input_payloads[reference_parts[0]] = (
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
        self.root_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(
                prefix=".canonical-3gb1-staging-",
                dir=self.root_dir,
            )
        ).resolve()
        try:
            (staging_dir / "inputs").mkdir(mode=0o700)
            write_private_new_file(
                staging_dir,
                ("project.json",),
                json.dumps(
                    self._meta_data(meta),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                ).encode("utf-8"),
                field="canonical_v2_metadata",
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
        safe_project_id = validate_identifier(project_id, "project_id")
        path = self.project_dir(safe_project_id) / "project.json"
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
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
            or raw["id"] != safe_project_id
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

    def list_projects(self) -> list[ProjectMeta]:
        """List only Project scopes whose exact v2 metadata is readable."""
        if not self.root_dir.exists():
            return []
        projects: list[ProjectMeta] = []
        for path in sorted(self.root_dir.iterdir()):
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                meta = self.load_meta(path.name)
            except (StoragePathError, ValueError):
                continue
            if meta is not None:
                projects.append(meta)
        return projects

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
        replace_private_regular_file(
            project_dir,
            ("project.json",),
            payload,
            field="project_metadata",
        )

    # ── seed project ──────────────────────────────────────────────────
