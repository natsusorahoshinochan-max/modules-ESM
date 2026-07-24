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

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.graph import Workflow, WorkflowEdge, WorkflowNode
from core.module_registry import ModuleRegistry

_logger = logging.getLogger(__name__)


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

    def __init__(self, root_dir: str | Path = "projects",
                 module_registry: ModuleRegistry | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.module_registry = module_registry

    def _project_dir(self, project_id: str) -> Path:
        return self.root_dir / project_id

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

    # ── seed project ──────────────────────────────────────────────────

    def ensure_seed_project(
        self,
        workflow_json_path: str | Path,
        ui_json_path: str | Path | None = None,
        name: str = "3GB1 Design Pipeline",
    ) -> ProjectMeta | None:
        """Create a seed project from a workflow JSON if it does not exist.

        The project ID is deterministic (UUID5 from workflow content hash)
        so repeated calls are idempotent. Validates all module_ids against
        the registry; on failure logs a warning and returns None.
        """
        wf_path = Path(workflow_json_path)
        if not wf_path.exists():
            _logger.warning("Seed workflow JSON not found: %s", wf_path)
            return None

        try:
            workflow_content = json.loads(wf_path.read_text())
        except (json.JSONDecodeError, Exception) as e:
            _logger.warning("Failed to parse seed workflow JSON: %s", e)
            return None

        # Deterministic project ID
        content_hash = json.dumps(workflow_content, sort_keys=True)
        project_id = str(uuid.uuid5(uuid.NAMESPACE_OID, content_hash))

        # Idempotent: skip if already exists
        if self._project_dir(project_id).exists():
            return self._load_meta(project_id)

        # Validate module_ids
        if self.module_registry is not None:
            for node in workflow_content.get("nodes", []):
                mid = node.get("module_id", "")
                if mid not in self.module_registry:
                    _logger.warning(
                        "Seed project references unknown module '%s'; skipping creation", mid
                    )
                    return None

        # Create project
        meta = ProjectMeta(id=project_id, name=name, seed=True)
        self._ensure_dir(project_id)
        self._save_meta(meta)

        # Copy workflow JSON directly
        (self._project_dir(project_id) / "workflow.json").write_text(
            wf_path.read_text()
        )

        # Copy or default UI JSON
        if ui_json_path and Path(ui_json_path).exists():
            (self._project_dir(project_id) / "ui.json").write_text(
                Path(ui_json_path).read_text()
            )
        else:
            self._save_ui(project_id, UIState())

        _logger.info("Created seed project '%s' (%s)", name, project_id)
        return meta

    # ── save ──────────────────────────────────────────────────────────

    def save(self, project_id: str, workflow: Workflow, ui: UIState) -> ProjectMeta:
        """Save workflow and UI state to an existing project."""
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
            if not d.is_dir():
                continue
            meta = self._load_meta(d.name)
            if meta:
                projects.append(meta)
        return projects

    # ── private helpers ───────────────────────────────────────────────

    def _save_meta(self, meta: ProjectMeta) -> None:
        self._ensure_dir(meta.id)
        data = {
            "id": meta.id,
            "name": meta.name,
            "created_at": meta.created_at,
            "modified_at": meta.modified_at,
            "workflow_version": meta.workflow_version,
            "module_dependencies": meta.module_dependencies,
            "seed": meta.seed,
        }
        (self._project_dir(meta.id) / "project.json").write_text(
            json.dumps(data, indent=2)
        )

    def _load_meta(self, project_id: str) -> ProjectMeta | None:
        raw = self._load_json(project_id, "project.json")
        if raw is None:
            return None
        return ProjectMeta(
            id=raw["id"],
            name=raw["name"],
            created_at=raw.get("created_at", ""),
            modified_at=raw.get("modified_at", ""),
            workflow_version=raw.get("workflow_version", "1.0"),
            module_dependencies=raw.get("module_dependencies", []),
            seed=raw.get("seed", False),
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
        (self._project_dir(project_id) / "workflow.json").write_text(
            json.dumps(data, indent=2)
        )

    def _save_ui(self, project_id: str, ui: UIState) -> None:
        self._ensure_dir(project_id)
        data = {
            "node_positions": ui.node_positions,
            "node_dimensions": ui.node_dimensions,
            "groupings": ui.groupings,
            "colors": ui.colors,
            "annotations": ui.annotations,
            "canvas_zoom": ui.canvas_zoom,
            "viewport": ui.viewport,
        }
        (self._project_dir(project_id) / "ui.json").write_text(
            json.dumps(data, indent=2)
        )

    def _load_json(self, project_id: str, filename: str) -> dict | None:
        """Load a JSON file from a project directory. Returns None if missing."""
        path = self._project_dir(project_id) / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, Exception):
            return None
