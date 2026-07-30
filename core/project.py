"""Project-scoped storage primitives for the sole supported v2 runtime."""

from __future__ import annotations

import hashlib
import json
import os
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
PROJECT_SCHEMA_VERSION = "2.0.0"


class CanonicalSeedError(RuntimeError):
    """The shipped canonical project cannot be safely installed."""


class ProtectedProjectError(PermissionError):
    """An ordinary write targeted the protected canonical project."""


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

    def input_path(self, project_id: str, uploaded_name: str) -> Path:
        """Resolve one uploaded file beneath the project's inputs directory."""
        name_parts = validate_relative_path(
            uploaded_name,
            "uploaded_name",
            allow_nested=False,
        )
        return contained_path(
            self.project_dir(project_id),
            "inputs",
            *name_parts,
            field="uploaded_name",
        )

    def publish_input(
        self,
        project_id: str,
        input_reference: str,
        payload: bytes,
    ) -> dict[str, Any]:
        """Publish one immutable owner-only Project input under an opaque ID."""
        self.assert_writable(project_id)
        safe_reference = validate_identifier(
            input_reference,
            "project_input_ref",
        )
        if type(payload) is not bytes or len(payload) > MAX_PROJECT_INPUT_BYTES:
            raise ValueError("Project input payload is invalid or too large")
        write_private_new_file(
            self.project_dir(project_id),
            ("inputs", safe_reference),
            payload,
            field="project_input_ref",
        )
        return {
            "project_input_ref": safe_reference,
            "size": len(payload),
            "content_digest": (
                "sha256:" + hashlib.sha256(payload).hexdigest()
            ),
        }

    def read_input(
        self,
        project_id: str,
        input_reference: str,
    ) -> tuple[dict[str, Any], bytes]:
        """Read and revalidate one immutable Project-scoped input snapshot."""
        safe_reference = validate_identifier(
            input_reference,
            "project_input_ref",
        )
        descriptor = open_private_regular_file(
            self.project_dir(project_id),
            ("inputs", safe_reference),
            field="project_input_ref",
        )
        try:
            before = os.fstat(descriptor)
            if before.st_size > MAX_PROJECT_INPUT_BYTES:
                raise ValueError("Project input exceeds the supported size")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                payload = source.read(MAX_PROJECT_INPUT_BYTES + 1)
            after = os.fstat(descriptor)
            stable_fields = (
                "st_dev",
                "st_ino",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            if (
                len(payload) > MAX_PROJECT_INPUT_BYTES
                or any(
                    getattr(before, field_name)
                    != getattr(after, field_name)
                    for field_name in stable_fields
                )
            ):
                raise ValueError("Project input changed while it was read")
        finally:
            os.close(descriptor)
        return (
            {
                "project_input_ref": safe_reference,
                "size": len(payload),
                "content_digest": (
                    "sha256:" + hashlib.sha256(payload).hexdigest()
                ),
            },
            payload,
        )

    def cache_dir(self, project_id: str) -> Path:
        """Resolve the shared content-addressed Cache directory for a project."""
        if self.cache_root is None:
            return contained_path(self.project_dir(project_id), "cache")
        return contained_path(
            self.cache_root,
            validate_identifier(project_id, "project_id"),
        )

    def output_dir(self, project_id: str, run_id: str) -> Path:
        """Resolve one run's artifact directory."""
        safe_run_id = validate_identifier(run_id, "run_id")
        if self.output_root is None:
            base = contained_path(self.project_dir(project_id), "outputs")
        else:
            base = contained_path(
                self.output_root,
                validate_identifier(project_id, "project_id"),
            )
        return contained_path(base, safe_run_id)

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
        workflow_json_path: str | Path,
        *,
        input_sources: Mapping[str, str | Path],
        name: str = "3GB1 Design Pipeline",
    ) -> ProjectMeta | None:
        """Install the maintained v2 seed without converting existing state."""
        from core.workflow_v2 import parse_workflow_document

        workflow_path = Path(workflow_json_path)
        if not workflow_path.is_file() or workflow_path.is_symlink():
            raise CanonicalSeedError(
                f"Canonical v2 Workflow JSON not found: {workflow_path}"
            )
        try:
            parsed = parse_workflow_document(
                json.loads(workflow_path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise CanonicalSeedError(
                "Canonical v2 Workflow is not an exact supported document"
            ) from error
        if (
            parsed.workflow_id != CANONICAL_3GB1_PROJECT_ID
            or not parsed.contract_lock
        ):
            raise CanonicalSeedError(
                "Canonical v2 Workflow identity or Contract Lock is invalid"
            )

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

        input_payloads: dict[str, bytes] = {}
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
                input_payloads[reference_parts[0]] = source.read_bytes()
            except OSError as error:
                raise CanonicalSeedError(
                    f"Canonical v2 input cannot be installed: {reference}"
                ) from error

        meta = ProjectMeta(
            id=CANONICAL_3GB1_PROJECT_ID,
            name=name,
            seed=True,
        )
        descriptor = {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "workflow_revision": 1,
            "workflow": parsed.to_public(),
        }
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
            write_private_new_file(
                staging_dir,
                ("workflow-v2.json",),
                json.dumps(
                    descriptor,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                ).encode("utf-8"),
                field="canonical_v2_workflow",
            )
            for reference, payload in input_payloads.items():
                write_private_new_file(
                    staging_dir,
                    ("inputs", reference),
                    payload,
                    field="canonical_v2_input",
                )
            if project_dir.exists():
                return None
            staging_dir.rename(project_dir)
        except (OSError, StoragePathError, ValueError) as error:
            raise CanonicalSeedError(
                "Canonical v2 Workflow cannot be installed safely"
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
