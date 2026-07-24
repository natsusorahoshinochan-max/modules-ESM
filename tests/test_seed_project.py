"""Tests for seed project mechanism (ticket 18d)."""

import json
import tempfile
import uuid
from pathlib import Path

import pytest

from core.project import ProjectManager, ProjectMeta


SAMPLE_WORKFLOW_JSON = """{
  "nodes": [
    {"node_id": "n1", "module_id": "stub.echo", "parameters": {}}
  ],
  "edges": []
}"""

SAMPLE_UI_JSON = """{
  "node_positions": {"n1": {"x": 100, "y": 100}},
  "canvas_zoom": 1.0,
  "viewport": {"x": 0, "y": 0}
}"""


class TestSeedProject:
    def test_creates_project_on_first_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write seed workflow and UI files
            wf_path = Path(tmpdir) / "workflow.json"
            ui_path = Path(tmpdir) / "ui.json"
            wf_path.write_text(SAMPLE_WORKFLOW_JSON)
            ui_path.write_text(SAMPLE_UI_JSON)

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)
            result = pm.ensure_seed_project(
                str(wf_path), str(ui_path), name="Test Seed"
            )

            assert result is not None
            assert isinstance(result, ProjectMeta)
            assert result.name == "Test Seed"
            assert result.seed is True

            # Verify files exist
            project_dir = Path(tmpdir) / "projects" / result.id
            assert project_dir.exists()
            assert (project_dir / "project.json").exists()
            assert (project_dir / "workflow.json").exists()
            assert (project_dir / "ui.json").exists()

            # Verify project.json has seed flag
            meta_content = json.loads(
                (project_dir / "project.json").read_text()
            )
            assert meta_content["seed"] is True

    def test_idempotent_second_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "workflow.json"
            wf_path.write_text(SAMPLE_WORKFLOW_JSON)

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)

            first = pm.ensure_seed_project(str(wf_path), name="Seed")
            second = pm.ensure_seed_project(str(wf_path), name="Seed")

            assert first is not None
            assert second is not None
            assert first.id == second.id

    def test_deterministic_project_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "workflow.json"
            wf_path.write_text(SAMPLE_WORKFLOW_JSON)

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            # Two separate ProjectManager instances with different roots
            pm1 = ProjectManager(root_dir=str(Path(tmpdir) / "projects1"),
                                 module_registry=mr)
            pm2 = ProjectManager(root_dir=str(Path(tmpdir) / "projects2"),
                                 module_registry=mr)

            r1 = pm1.ensure_seed_project(str(wf_path))
            r2 = pm2.ensure_seed_project(str(wf_path))

            assert r1 is not None
            assert r2 is not None
            assert r1.id == r2.id, "Same workflow should produce same UUID5"

    def test_returns_none_for_missing_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)
            result = pm.ensure_seed_project(
                str(Path(tmpdir) / "nonexistent.json")
            )
            assert result is None

    def test_returns_none_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "bad.json"
            wf_path.write_text("{invalid json")

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)
            result = pm.ensure_seed_project(str(wf_path))
            assert result is None

    def test_returns_none_for_unknown_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_wf = """{
              "nodes": [
                {"node_id": "n1", "module_id": "nonexistent.module", "parameters": {}}
              ],
              "edges": []
            }"""
            wf_path = Path(tmpdir) / "workflow.json"
            wf_path.write_text(bad_wf)

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)
            result = pm.ensure_seed_project(str(wf_path))
            assert result is None

    def test_seed_project_in_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "workflow.json"
            wf_path.write_text(SAMPLE_WORKFLOW_JSON)

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)
            pm.ensure_seed_project(str(wf_path), name="Seed Example")

            projects = pm.list_projects()
            assert len(projects) == 1
            assert projects[0].name == "Seed Example"
            assert projects[0].seed is True

    def test_no_registry_allows_creation(self) -> None:
        """Without a registry, skip validation and create project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "workflow.json"
            wf_path.write_text(SAMPLE_WORKFLOW_JSON)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"))
            result = pm.ensure_seed_project(str(wf_path), name="No Registry")

            # Without registry, validation is skipped, so project is created
            assert result is not None
            assert result.seed is True

    def test_load_meta_preserves_seed_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "workflow.json"
            wf_path.write_text(SAMPLE_WORKFLOW_JSON)

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)
            created = pm.ensure_seed_project(str(wf_path), name="Test")
            assert created is not None

            # Load it back
            loaded = pm.load_meta(created.id)
            assert loaded is not None
            assert loaded.seed is True
