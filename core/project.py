"""Project persistence: create, save, load with three-file layout.

Directory layout per project:
    projects/<project_id>/
        project.json    — metadata (name, timestamps, module dependencies)
        workflow.json   — computation graph (nodes, edges, parameters)
        ui.json         — presentation state (positions, zoom, annotations)
        inputs/         — uploaded input files
        outputs/        — exported output files
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core.graph import Workflow, WorkflowEdge, WorkflowNode
from core.module_registry import ModuleRegistry
from core.storage import (
    StoragePathError,
    contained_path,
    open_private_regular_file,
    validate_identifier,
    validate_relative_path,
    write_private_new_file,
)

_logger = logging.getLogger(__name__)

CANONICAL_3GB1_PROJECT_ID = "canonical-3gb1"
MAX_PROJECT_INPUT_BYTES = 64 * 1024 * 1024


class CanonicalSeedError(RuntimeError):
    """The shipped canonical project cannot be safely installed."""


class ProtectedProjectError(PermissionError):
    """An ordinary write targeted the protected canonical project."""


@dataclass
class ProjectMeta:
    """Metadata for a saved project."""

    id: str
    name: str
    created_at: str = ""
    modified_at: str = ""
    workflow_version: str = "1.0"
    module_dependencies: list[str] = field(default_factory=list)
    seed: bool = False
    legacy_seed: bool = False
    legacy_source_hash: str | None = None
    legacy_metadata_archive: str | None = None
    legacy_metadata_archive_recorded: bool = field(
        default=False,
        repr=False,
        compare=False,
    )
    seed_version: str | None = None
    seed_content_hash: str | None = None

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.modified_at:
            self.modified_at = now


@dataclass
class UIState:
    """Presentation state for a workflow canvas."""

    node_positions: dict[str, dict[str, float]] = field(default_factory=dict)
    node_dimensions: dict[str, dict[str, float]] = field(default_factory=dict)
    groupings: list[dict] = field(default_factory=list)
    colors: dict[str, str] = field(default_factory=dict)
    annotations: list[dict] = field(default_factory=list)
    canvas_zoom: float = 1.0
    viewport: dict[str, float] = field(default_factory=dict)


class ProjectManager:
    """Manages project persistence: create, save, load.

    Projects are stored under a root directory (default: ./projects).
    Each project is a directory with project.json, workflow.json, ui.json.
    """

    def __init__(
        self,
        root_dir: str | Path = "projects",
        module_registry: ModuleRegistry | None = None,
        *,
        cache_root: str | Path | None = None,
        output_root: str | Path | None = None,
        run_root: str | Path | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.module_registry = module_registry
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

    def cache_path(
        self,
        project_id: str,
        node_id: str,
        cache_key: str,
    ) -> Path:
        """Resolve one Node's content-addressed Cache entry."""
        safe_node_id = validate_identifier(node_id, "node_id")
        safe_cache_key = validate_identifier(cache_key, "cache_key")
        return contained_path(
            self.cache_node_dir(project_id, safe_node_id),
            f"{safe_cache_key}.pkl",
        )

    def cache_node_dir(self, project_id: str, node_id: str) -> Path:
        """Resolve one Node's unambiguous Cache namespace."""
        return contained_path(
            self.cache_dir(project_id),
            validate_identifier(node_id, "node_id"),
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

    def output_path(
        self,
        project_id: str,
        run_id: str,
        artifact_name: str,
    ) -> Path:
        """Resolve a requested artifact beneath one run's output namespace."""
        artifact_parts = validate_relative_path(
            artifact_name,
            "artifact_name",
        )
        return contained_path(
            self.output_dir(project_id, run_id),
            *artifact_parts,
            field="artifact_name",
        )

    def output_reference_path(
        self,
        project_id: str,
        output_reference: str,
    ) -> Path:
        """Resolve a hybrid ``run_id/artifact`` output reference."""
        reference_parts = validate_relative_path(
            output_reference,
            "output_path",
        )
        if len(reference_parts) < 2:
            raise StoragePathError(
                "output_path",
                "Invalid output_path",
            )
        run_id, *artifact_parts = reference_parts
        return self.output_path(
            project_id,
            run_id,
            "/".join(artifact_parts),
        )

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
        """Create a new project with empty workflow and UI state."""
        project_id = str(uuid.uuid4())
        meta = ProjectMeta(id=project_id, name=name)
        self._ensure_dir(project_id)
        self._save_meta(meta)
        self._save_workflow(project_id, Workflow())
        self._save_ui(project_id, UIState())
        return meta

    def assert_writable(self, project_id: str) -> None:
        """Reject ordinary content or metadata writes to the canonical ID."""
        safe_project_id = validate_identifier(project_id, "project_id")
        if safe_project_id == CANONICAL_3GB1_PROJECT_ID:
            raise ProtectedProjectError(
                "The canonical 3GB1 project is read-only"
            )

    # ── seed project ──────────────────────────────────────────────────

    def ensure_seed_project(
        self,
        workflow_json_path: str | Path,
        ui_json_path: str | Path | None = None,
        name: str = "3GB1 Design Pipeline",
        *,
        version: str = "1",
        input_sources: Mapping[str, str | Path] | None = None,
        additional_input_sources: (
            Mapping[str, str | Path] | None
        ) = None,
    ) -> ProjectMeta:
        """Install or upgrade the protected canonical 3GB1 project.

        The project ID is the stable semantic identity ``canonical-3gb1``,
        independent of serialized Workflow content. The shipped Workflow is
        validated against the current Module Registry before storage changes.
        """
        wf_path = Path(workflow_json_path)
        if not wf_path.exists() or wf_path.is_symlink():
            raise CanonicalSeedError(
                f"Canonical Workflow JSON not found: {wf_path}"
            )
        if not isinstance(version, str) or not version:
            raise CanonicalSeedError(
                "Canonical content version must be a non-empty string"
            )

        try:
            workflow_content = json.loads(wf_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise CanonicalSeedError(
                f"Failed to parse canonical Workflow JSON: {error}"
            ) from error

        self._validate_canonical_workflow(workflow_content)
        project_id = CANONICAL_3GB1_PROJECT_ID
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._recover_interrupted_canonical_publish()
        self._demote_noncanonical_seed_claims()

        seed_inputs: list[tuple[Path, tuple[str, ...]]] = []
        for node in workflow_content.get("nodes", []):
            if node.get("module_id") not in {
                "import.sequence",
                "import.structure",
            }:
                continue
            input_reference = node.get("parameters", {}).get("file_path", "")
            try:
                destination_parts = validate_relative_path(
                    input_reference,
                    "input_path",
                )
            except StoragePathError as error:
                raise CanonicalSeedError(
                    f"Unsafe canonical input reference: {error}"
                ) from error
            if destination_parts[:1] == ("inputs",):
                destination_parts = destination_parts[1:]
            configured_source = (
                input_sources.get(input_reference)
                if input_sources is not None
                else None
            )
            if configured_source is not None:
                source = Path(configured_source)
            else:
                try:
                    source = contained_path(
                        Path.cwd(),
                        *validate_relative_path(
                            input_reference,
                            "input_path",
                        ),
                        field="input_path",
                    )
                except StoragePathError as error:
                    raise CanonicalSeedError(
                        f"Unsafe canonical input reference: {error}"
                    ) from error
            if (
                not source.is_file()
                or source.is_symlink()
                or not destination_parts
            ):
                raise CanonicalSeedError(
                    f"Canonical input file not found: {input_reference}"
                )
            seed_inputs.append((source, destination_parts))
        for reference, configured_source in (
            additional_input_sources or {}
        ).items():
            try:
                destination_parts = validate_relative_path(
                    reference,
                    "input_path",
                    allow_nested=False,
                )
            except StoragePathError as error:
                raise CanonicalSeedError(
                    f"Unsafe canonical input reference: {error}"
                ) from error
            source = Path(configured_source)
            if (
                not source.is_file()
                or source.is_symlink()
                or not destination_parts
            ):
                raise CanonicalSeedError(
                    f"Canonical input file not found: {reference}"
                )
            seed_inputs.append((source, destination_parts))

        ui_content: dict[str, Any]
        if ui_json_path is not None:
            ui_path = Path(ui_json_path)
            if not ui_path.exists() or ui_path.is_symlink():
                raise CanonicalSeedError(
                    f"Canonical UI state not found: {ui_path}"
                )
            try:
                loaded_ui = json.loads(ui_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise CanonicalSeedError(
                    f"Failed to parse canonical UI state: {error}"
                ) from error
            if not isinstance(loaded_ui, dict):
                raise CanonicalSeedError(
                    "Canonical UI state must be a JSON object"
                )
            ui_content = loaded_ui
        else:
            ui_content = self._ui_data(UIState())

        expected_hash = self._canonical_content_hash(
            workflow_content,
            ui_content,
            seed_inputs,
        )
        expected_dependencies = sorted({
            node["module_id"]
            for node in workflow_content["nodes"]
        })
        project_dir = self.project_dir(project_id)
        if project_dir.exists() and not project_dir.is_dir():
            raise CanonicalSeedError(
                "Canonical project path is not a directory"
            )
        try:
            existing_meta = self._load_meta(project_id)
        except StoragePathError:
            existing_meta = None
        installed_hash = (
            self._installed_content_hash(project_dir)
            if project_dir.exists()
            else None
        )
        metadata_is_current = (
            existing_meta is not None
            and existing_meta.seed is True
            and existing_meta.legacy_seed is False
            and existing_meta.name == name
            and existing_meta.workflow_version == "1.0"
            and existing_meta.seed_content_hash == expected_hash
            and existing_meta.seed_version == version
            and existing_meta.module_dependencies == expected_dependencies
        )
        if (
            metadata_is_current
            and installed_hash == expected_hash
        ):
            return existing_meta
        if project_dir.exists():
            self._preserve_legacy_project(project_dir, existing_meta)

        def provision_seed_inputs(destination_project_dir: Path) -> None:
            for source, destination_parts in seed_inputs:
                destination = contained_path(
                    destination_project_dir,
                    "inputs",
                    *destination_parts,
                    field="input_path",
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)

        created_at = (
            existing_meta.created_at
            if existing_meta is not None
            else ""
        )
        meta = ProjectMeta(
            id=project_id,
            name=name,
            created_at=created_at,
            seed=True,
            seed_version=version,
            seed_content_hash=expected_hash,
            module_dependencies=expected_dependencies,
        )
        self.root_dir.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(
            prefix="canonical-stage-",
            dir=self.root_dir,
        ))
        try:
            staged_inputs = stage / "inputs"
            if staged_inputs.exists():
                if staged_inputs.is_symlink():
                    staged_inputs.unlink()
                else:
                    shutil.rmtree(staged_inputs)
            staged_inputs.mkdir()
            (stage / "outputs").mkdir(exist_ok=True)
            provision_seed_inputs(stage)
            self._write_json(stage / "project.json", self._meta_data(meta))
            self._write_json(stage / "workflow.json", workflow_content)
            self._write_json(stage / "ui.json", ui_content)
            if self._installed_content_hash(stage) != expected_hash:
                raise CanonicalSeedError(
                    "Canonical content changed while it was staged"
                )
            self._replace_project_directory(stage, project_dir)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

        _logger.info("Created seed project '%s' (%s)", name, project_id)
        return meta

    def install_seed_workflow_v2(
        self,
        workflow_json_path: str | Path,
        *,
        input_sources: Mapping[str, str | Path],
    ) -> None:
        """Install the exact protected v2 Workflow beside the legacy seed.

        This is the only write path for the maintained protected v2 snapshot;
        ordinary public authoring remains forbidden by ``assert_writable``.
        """
        project_id = CANONICAL_3GB1_PROJECT_ID
        meta = self.load_meta(project_id)
        if meta is None or not meta.seed or meta.legacy_seed:
            raise CanonicalSeedError(
                "Canonical v2 Workflow requires the protected seed project"
            )
        path = Path(workflow_json_path)
        if not path.is_file() or path.is_symlink():
            raise CanonicalSeedError(
                f"Canonical v2 Workflow JSON not found: {path}"
            )
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            from core.workflow_v2 import parse_workflow_document

            parsed = parse_workflow_document(workflow)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise CanonicalSeedError(
                "Canonical v2 Workflow is not an exact supported document"
            ) from error
        if (
            parsed.workflow_id != project_id
            or not parsed.contract_lock
        ):
            raise CanonicalSeedError(
                "Canonical v2 Workflow identity or Contract Lock is invalid"
            )
        project_dir = self.project_dir(project_id)
        for node in parsed.nodes:
            reference = node.node_parameters.get("project_input_ref")
            if reference is None:
                continue
            if not isinstance(reference, str):
                raise CanonicalSeedError(
                    "Canonical v2 input reference is invalid"
                )
            source_value = input_sources.get(reference)
            if source_value is None:
                raise CanonicalSeedError(
                    f"Canonical v2 input source is missing: {reference}"
                )
            source = Path(source_value)
            if not source.is_file() or source.is_symlink():
                raise CanonicalSeedError(
                    f"Canonical v2 input file is unavailable: {reference}"
                )
            destination = self.input_path(project_id, reference)
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = source.read_bytes()
            if destination.is_symlink():
                raise CanonicalSeedError(
                    f"Canonical v2 input target is unsafe: {reference}"
                )
            if not destination.exists() or destination.read_bytes() != payload:
                temporary = destination.with_name(
                    f".{destination.name}.canonical-v2.tmp"
                )
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
                try:
                    temporary.write_bytes(payload)
                    os.replace(temporary, destination)
                finally:
                    if temporary.exists():
                        temporary.unlink()
        target = project_dir / "workflow-v2.json"
        descriptor = {
            "schema_version": "2.0.0",
            "workflow_revision": 1,
            "workflow": parsed.to_public(),
        }
        if target.is_symlink():
            raise CanonicalSeedError(
                "Canonical v2 Workflow storage target is unsafe"
            )
        if target.is_file():
            try:
                if json.loads(target.read_text(encoding="utf-8")) == descriptor:
                    return
            except (OSError, json.JSONDecodeError):
                pass
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".canonical-workflow-v2-",
            suffix=".json",
            dir=project_dir,
            text=True,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
            ) as stream:
                json.dump(
                    descriptor,
                    stream,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        if path.is_symlink():
            path.unlink()
        path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f"{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _canonical_content_hash(
        workflow: dict[str, Any],
        ui: dict[str, Any],
        seed_inputs: list[tuple[Path, tuple[str, ...]]],
    ) -> str:
        hasher = hashlib.sha256()
        for label, payload in (("workflow", workflow), ("ui", ui)):
            hasher.update(label.encode())
            hasher.update(json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode())
        for source, destination_parts in sorted(
            seed_inputs,
            key=lambda item: item[1],
        ):
            hasher.update("/".join(destination_parts).encode())
            hasher.update(source.read_bytes())
        return f"sha256:{hasher.hexdigest()}"

    @staticmethod
    def _installed_content_hash(project_dir: Path) -> str | None:
        try:
            if (
                (project_dir / "workflow.json").is_symlink()
                or (project_dir / "ui.json").is_symlink()
            ):
                return None
            workflow = json.loads(
                (project_dir / "workflow.json").read_text()
            )
            ui = json.loads((project_dir / "ui.json").read_text())
            input_files = []
            inputs_dir = project_dir / "inputs"
            if inputs_dir.is_symlink():
                return None
            if inputs_dir.exists():
                for path in sorted(inputs_dir.rglob("*")):
                    if path.is_symlink():
                        return None
                    if path.is_dir():
                        continue
                    if not path.is_file():
                        return None
                    input_files.append((
                        path,
                        path.relative_to(inputs_dir).parts,
                    ))
            return ProjectManager._canonical_content_hash(
                workflow,
                ui,
                input_files,
            )
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _replace_project_directory(stage: Path, target: Path) -> None:
        if not target.exists():
            os.replace(stage, target)
            return
        backup = target.with_name(
            f"{CANONICAL_3GB1_PROJECT_ID}-backup"
        )
        if backup.exists() or backup.is_symlink():
            raise CanonicalSeedError(
                "Interrupted canonical publication requires recovery"
            )
        os.replace(target, backup)
        try:
            os.replace(stage, target)
        except Exception:
            os.replace(backup, target)
            raise
        else:
            shutil.rmtree(backup)

    def _recover_interrupted_canonical_publish(self) -> None:
        target = self.root_dir / CANONICAL_3GB1_PROJECT_ID
        backup = self.root_dir / f"{CANONICAL_3GB1_PROJECT_ID}-backup"
        if backup.is_symlink():
            raise CanonicalSeedError(
                "Unsafe canonical publication backup"
            )
        if not backup.exists():
            return
        if not backup.is_dir():
            raise CanonicalSeedError(
                "Invalid canonical publication backup"
            )
        if not target.exists():
            os.replace(backup, target)
            return
        if target.is_symlink() or not target.is_dir():
            raise CanonicalSeedError(
                "Invalid canonical project path during recovery"
            )
        try:
            backup_meta = self._load_meta(backup.name)
        except StoragePathError:
            backup_meta = None
        self._preserve_legacy_project(backup, backup_meta)
        shutil.rmtree(backup)

    def _preserve_legacy_project(
        self,
        source: Path,
        source_meta: ProjectMeta | None,
    ) -> ProjectMeta:
        identity = self._legacy_identity_hash(source)
        legacy_id_base = f"legacy-3gb1-{identity[:24]}"
        legacy_id = legacy_id_base
        collision_index = 1
        legacy_path = self.root_dir / legacy_id
        while legacy_path.exists() or legacy_path.is_symlink():
            try:
                existing = self._load_meta(legacy_id)
            except StoragePathError:
                existing = None
            if (
                existing is not None
                and existing.legacy_seed
                and existing.legacy_source_hash == identity
                and self._legacy_snapshot_identity_hash(
                    legacy_path,
                    existing,
                ) == identity
            ):
                return existing
            legacy_id = f"{legacy_id_base}-{collision_index}"
            collision_index += 1
            legacy_path = self.root_dir / legacy_id

        legacy_meta = ProjectMeta(
            id=legacy_id,
            name=(
                f"{source_meta.name} (legacy)"
                if source_meta is not None
                else "3GB1 project (legacy)"
            ),
            created_at=(
                source_meta.created_at
                if source_meta is not None
                else ""
            ),
            workflow_version=(
                source_meta.workflow_version
                if source_meta is not None
                else "1.0"
            ),
            module_dependencies=(
                list(source_meta.module_dependencies)
                if source_meta is not None
                else []
            ),
            seed=False,
            legacy_seed=True,
            legacy_source_hash=identity,
            legacy_metadata_archive_recorded=True,
            seed_version=(
                source_meta.seed_version
                if source_meta is not None
                else None
            ),
            seed_content_hash=(
                source_meta.seed_content_hash
                if source_meta is not None
                else None
            ),
        )
        stage = Path(tempfile.mkdtemp(
            prefix="legacy-stage-",
            dir=self.root_dir,
        ))
        try:
            shutil.copytree(
                source,
                stage,
                dirs_exist_ok=True,
                symlinks=True,
            )
            staged_meta = stage / "project.json"
            if staged_meta.exists() or staged_meta.is_symlink():
                archive_index = 0
                while True:
                    archive_name = (
                        "legacy-project.json"
                        if archive_index == 0
                        else f"legacy-project-{archive_index}.json"
                    )
                    archive_path = stage / archive_name
                    if (
                        not archive_path.exists()
                        and not archive_path.is_symlink()
                    ):
                        break
                    archive_index += 1
                os.replace(
                    staged_meta,
                    archive_path,
                )
                legacy_meta.legacy_metadata_archive = archive_name
            self._write_json(staged_meta, self._meta_data(legacy_meta))
            if (
                self._legacy_snapshot_identity_hash(stage, legacy_meta)
                != identity
            ):
                raise CanonicalSeedError(
                    "Legacy project changed while it was staged"
                )
            os.replace(stage, legacy_path)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return legacy_meta

    @staticmethod
    def _legacy_identity_hash(project_dir: Path) -> str:
        entries = [
            (path, path.relative_to(project_dir).parts)
            for path in project_dir.rglob("*")
        ]
        return ProjectManager._legacy_entries_identity_hash(entries)

    @staticmethod
    def _legacy_snapshot_identity_hash(
        project_dir: Path,
        meta: ProjectMeta,
    ) -> str | None:
        archive_name = meta.legacy_metadata_archive
        if (
            archive_name is None
            and not meta.legacy_metadata_archive_recorded
        ):
            fallback = project_dir / "legacy-project.json"
            if fallback.exists() or fallback.is_symlink():
                archive_name = fallback.name
        if archive_name is not None:
            try:
                archive_parts = validate_relative_path(
                    archive_name,
                    "legacy_metadata_archive",
                    allow_nested=False,
                )
            except StoragePathError:
                return None
            if len(archive_parts) != 1:
                return None
        else:
            archive_parts = None

        entries: list[tuple[Path, tuple[str, ...]]] = []
        archive_found = archive_parts is None
        for path in project_dir.rglob("*"):
            relative_parts = path.relative_to(project_dir).parts
            if relative_parts == ("project.json",):
                continue
            if archive_parts is not None and relative_parts == archive_parts:
                relative_parts = ("project.json",)
                archive_found = True
            entries.append((path, relative_parts))
        if not archive_found:
            return None
        return ProjectManager._legacy_entries_identity_hash(entries)

    @staticmethod
    def _legacy_entries_identity_hash(
        entries: list[tuple[Path, tuple[str, ...]]],
    ) -> str:
        hasher = hashlib.sha256()
        for path, relative_parts in sorted(
            entries,
            key=lambda item: item[1],
        ):
            relative = "/".join(relative_parts).encode()
            hasher.update(len(relative).to_bytes(8, "big"))
            hasher.update(relative)
            if path.is_symlink():
                target = os.readlink(path).encode()
                hasher.update(b"L")
                hasher.update(len(target).to_bytes(8, "big"))
                hasher.update(target)
            elif path.is_file():
                content = path.read_bytes()
                hasher.update(b"F")
                hasher.update(len(content).to_bytes(8, "big"))
                hasher.update(content)
            elif path.is_dir():
                hasher.update(b"D")
        return hasher.hexdigest()

    def _demote_noncanonical_seed_claims(self) -> None:
        for project_path in self.root_dir.iterdir():
            if (
                not project_path.is_dir()
                or project_path.is_symlink()
                or project_path.name == CANONICAL_3GB1_PROJECT_ID
            ):
                continue
            meta_path = project_path / "project.json"
            if not meta_path.is_file() or meta_path.is_symlink():
                continue
            try:
                raw = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict) or not raw.get("seed", False):
                continue
            raw["id"] = project_path.name
            raw["seed"] = False
            raw["legacy_seed"] = True
            self._atomic_write_json(meta_path, raw)

    def _validate_canonical_workflow(
        self,
        workflow_content: Any,
    ) -> Workflow:
        """Build and authoritatively validate the shipped Workflow."""
        if self.module_registry is None:
            raise CanonicalSeedError(
                "Canonical Workflow validation requires a Module Registry"
            )
        if not isinstance(workflow_content, dict):
            raise CanonicalSeedError(
                "Canonical Workflow must be a JSON object"
            )
        raw_nodes = workflow_content.get("nodes")
        raw_edges = workflow_content.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise CanonicalSeedError(
                "Canonical Workflow nodes and edges must be lists"
            )

        workflow = Workflow()
        try:
            for raw_node in raw_nodes:
                if not isinstance(raw_node, dict):
                    raise ValueError("Workflow Node must be an object")
                node = WorkflowNode(
                    node_id=raw_node["node_id"],
                    module_id=raw_node["module_id"],
                    module_version=raw_node.get("module_version", "1.0.0"),
                    parameters=raw_node.get("parameters", {}),
                )
                workflow.add_node(node)
            for raw_edge in raw_edges:
                if not isinstance(raw_edge, dict):
                    raise ValueError("Workflow Edge must be an object")
                workflow.add_edge(WorkflowEdge(
                    source_node_id=raw_edge["source_node_id"],
                    source_port=raw_edge["source_port"],
                    target_node_id=raw_edge["target_node_id"],
                    target_port=raw_edge["target_port"],
                ))
        except (KeyError, TypeError, ValueError) as error:
            raise CanonicalSeedError(
                f"Malformed canonical Workflow: {error}"
            ) from error

        validation = workflow.validate(self.module_registry)
        if not validation.valid:
            details = "; ".join(
                f"{error.kind.value}: {error.message}"
                for error in validation.errors
            )
            raise CanonicalSeedError(
                f"Canonical Workflow validation failed: {details}"
            )
        return workflow

    # ── save ──────────────────────────────────────────────────────────

    def save(self, project_id: str, workflow: Workflow, ui: UIState) -> ProjectMeta:
        """Save workflow and UI state to an existing project."""
        self.assert_writable(project_id)
        meta = self._load_meta(project_id)
        if meta is None:
            raise ValueError(f"Project '{project_id}' not found")

        meta.modified_at = datetime.now(timezone.utc).isoformat()
        meta.module_dependencies = sorted(
            set(n.module_id for n in workflow.nodes.values())
        )

        self._save_meta(meta)
        self._save_workflow(project_id, workflow)
        self._save_ui(project_id, ui)
        return meta

    # ── load ──────────────────────────────────────────────────────────

    def load_meta(self, project_id: str) -> ProjectMeta | None:
        """Load project metadata only."""
        return self._load_meta(project_id)

    def load_workflow(self, project_id: str) -> Workflow:
        """Load workflow from project, with missing-module handling.

        If a workflow node references a module not in the registry, the node
        is still created as a placeholder with all parameters and connections
        preserved, but marked as unavailable.
        """
        raw = self._load_json(project_id, "workflow.json")
        if raw is None:
            return Workflow()

        workflow = Workflow()
        for n in raw.get("nodes", []):
            module_id = n["module_id"]
            available = False
            if self.module_registry is not None and module_id in self.module_registry:
                available = True

            node = WorkflowNode(
                node_id=n["node_id"],
                module_id=module_id,
                module_version=n.get("module_version", "1.0.0"),
                parameters=n.get("parameters", {}),
            )
            object.__setattr__(node, "available", available)
            workflow.add_node(node)

        for e in raw.get("edges", []):
            edge = WorkflowEdge(
                source_node_id=e["source_node_id"],
                source_port=e["source_port"],
                target_node_id=e["target_node_id"],
                target_port=e["target_port"],
            )
            workflow.add_edge(edge)

        return workflow

    def load_ui(self, project_id: str) -> UIState:
        """Load UI state from project.

        If ui.json is missing or corrupted, returns default UIState so that
        nodes auto-layout on the canvas without data loss.
        """
        raw = self._load_json(project_id, "ui.json")
        if raw is None:
            return UIState()
        try:
            return UIState(
                node_positions=raw.get("node_positions", {}),
                node_dimensions=raw.get("node_dimensions", {}),
                groupings=raw.get("groupings", []),
                colors=raw.get("colors", {}),
                annotations=raw.get("annotations", []),
                canvas_zoom=raw.get("canvas_zoom", 1.0),
                viewport=raw.get("viewport", {}),
            )
        except Exception:
            return UIState()

    def list_projects(self) -> list[ProjectMeta]:
        """List all saved projects."""
        if not self.root_dir.exists():
            return []
        projects = []
        for d in sorted(self.root_dir.iterdir()):
            if not d.is_dir() or d.is_symlink():
                continue
            try:
                meta = self._load_meta(d.name)
            except StoragePathError:
                continue
            if meta:
                projects.append(meta)
        return projects

    # ── private helpers ───────────────────────────────────────────────

    @staticmethod
    def _meta_data(meta: ProjectMeta) -> dict[str, Any]:
        return {
            "id": meta.id,
            "name": meta.name,
            "created_at": meta.created_at,
            "modified_at": meta.modified_at,
            "workflow_version": meta.workflow_version,
            "module_dependencies": meta.module_dependencies,
            "seed": meta.seed,
            "legacy_seed": meta.legacy_seed,
            "legacy_source_hash": meta.legacy_source_hash,
            "legacy_metadata_archive": meta.legacy_metadata_archive,
            "seed_version": meta.seed_version,
            "seed_content_hash": meta.seed_content_hash,
        }

    def _save_meta(self, meta: ProjectMeta) -> None:
        self._ensure_dir(meta.id)
        self._atomic_write_json(
            self._project_dir(meta.id) / "project.json",
            self._meta_data(meta),
        )

    def _load_meta(self, project_id: str) -> ProjectMeta | None:
        raw = self._load_json(project_id, "project.json")
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("name"), str)
        ):
            return None
        raw_id = raw.get("id")
        canonical = (
            project_id == CANONICAL_3GB1_PROJECT_ID
            and raw_id == CANONICAL_3GB1_PROJECT_ID
            and raw.get("seed", False) is True
        )
        legacy_seed = bool(raw.get("legacy_seed", False)) or (
            bool(raw.get("seed", False)) and not canonical
        )
        return ProjectMeta(
            id=project_id,
            name=raw["name"],
            created_at=raw.get("created_at", ""),
            modified_at=raw.get("modified_at", ""),
            workflow_version=raw.get("workflow_version", "1.0"),
            module_dependencies=raw.get("module_dependencies", []),
            seed=canonical,
            legacy_seed=legacy_seed,
            legacy_source_hash=raw.get("legacy_source_hash"),
            legacy_metadata_archive=raw.get("legacy_metadata_archive"),
            legacy_metadata_archive_recorded=(
                "legacy_metadata_archive" in raw
            ),
            seed_version=raw.get("seed_version"),
            seed_content_hash=raw.get("seed_content_hash"),
        )

    def _save_workflow(self, project_id: str, workflow: Workflow) -> None:
        self._ensure_dir(project_id)
        data = {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "module_id": n.module_id,
                    "module_version": n.module_version,
                    "parameters": n.parameters,
                }
                for n in workflow.nodes.values()
            ],
            "edges": [
                {
                    "source_node_id": e.source_node_id,
                    "source_port": e.source_port,
                    "target_node_id": e.target_node_id,
                    "target_port": e.target_port,
                }
                for e in workflow.edges
            ],
        }
        self._atomic_write_json(
            self._project_dir(project_id) / "workflow.json",
            data,
        )

    @staticmethod
    def _ui_data(ui: UIState) -> dict[str, Any]:
        return {
            "node_positions": ui.node_positions,
            "node_dimensions": ui.node_dimensions,
            "groupings": ui.groupings,
            "colors": ui.colors,
            "annotations": ui.annotations,
            "canvas_zoom": ui.canvas_zoom,
            "viewport": ui.viewport,
        }

    def _save_ui(self, project_id: str, ui: UIState) -> None:
        self._ensure_dir(project_id)
        self._atomic_write_json(
            self._project_dir(project_id) / "ui.json",
            self._ui_data(ui),
        )

    def _load_json(self, project_id: str, filename: str) -> dict | None:
        """Load a JSON file from a project directory. Returns None if missing."""
        path = contained_path(
            self._project_dir(project_id),
            filename,
            field="project_file",
        )
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, Exception):
            return None
