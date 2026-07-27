"""Tests for seed project mechanism (ticket 18d)."""

import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from core.project import (
    CANONICAL_3GB1_PROJECT_ID,
    CanonicalSeedError,
    ProtectedProjectError,
    ProjectManager,
    ProjectMeta,
    UIState,
)


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
    def test_shipped_canonical_workflow_validates_at_creation(
        self,
        tmp_path: Path,
    ) -> None:
        from core import TypeRegistry, ModuleRegistry, discover_modules

        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        manager = ProjectManager(
            root_dir=tmp_path / "projects",
            module_registry=module_registry,
        )

        project = manager.ensure_seed_project(
            Path("examples/3gb1_pipeline.json"),
            Path("examples/3gb1_pipeline_ui.json"),
        )

        assert project is not None
        assert project.id == CANONICAL_3GB1_PROJECT_ID

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

    def test_clean_canonical_content_upgrades_without_changing_identity(
        self,
        tmp_path: Path,
    ) -> None:
        workflow_path = tmp_path / "workflow.json"
        workflow_path.write_text(SAMPLE_WORKFLOW_JSON)

        from core import TypeRegistry, ModuleRegistry, discover_modules
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        manager = ProjectManager(
            root_dir=tmp_path / "projects",
            module_registry=module_registry,
        )

        first = manager.ensure_seed_project(
            workflow_path,
            name="Seed",
            version="1",
        )
        assert first is not None
        retained_output = (
            manager.project_dir(first.id) / "outputs" / "retained.txt"
        )
        retained_output.write_text("existing run output")

        workflow_path.write_text(
            SAMPLE_WORKFLOW_JSON.replace(
                '"parameters": {}',
                '"parameters": {"prefix": "upgraded"}',
            )
        )
        upgraded = manager.ensure_seed_project(
            workflow_path,
            name="Seed",
            version="2",
        )

        assert upgraded is not None
        assert upgraded.id == first.id == CANONICAL_3GB1_PROJECT_ID
        assert upgraded.seed_version == "2"
        assert (
            manager.load_workflow(upgraded.id)
            .nodes["n1"]
            .parameters["prefix"]
            == "upgraded"
        )
        projects = manager.list_projects()
        legacy = next(project for project in projects if project.legacy_seed)
        assert (
            manager.project_dir(legacy.id)
            / "outputs"
            / "retained.txt"
        ).read_text() == "existing run output"
        assert sum(project.seed for project in projects) == 1

    def test_user_modified_canonical_is_preserved_as_legacy(
        self,
        tmp_path: Path,
    ) -> None:
        workflow_path = tmp_path / "workflow.json"
        workflow_path.write_text(SAMPLE_WORKFLOW_JSON)

        from core import TypeRegistry, ModuleRegistry, discover_modules
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        manager = ProjectManager(
            root_dir=tmp_path / "projects",
            module_registry=module_registry,
        )
        created = manager.ensure_seed_project(workflow_path, version="1")
        assert created is not None

        installed_workflow = (
            manager.project_dir(created.id) / "workflow.json"
        )
        user_modified = json.loads(installed_workflow.read_text())
        user_modified["nodes"][0]["parameters"] = {"prefix": "user edit"}
        installed_workflow.write_text(json.dumps(user_modified))

        workflow_path.write_text(
            SAMPLE_WORKFLOW_JSON.replace(
                '"parameters": {}',
                '"parameters": {"prefix": "shipped upgrade"}',
            )
        )
        manager.ensure_seed_project(workflow_path, version="2")

        projects = manager.list_projects()
        canonical = next(
            project
            for project in projects
            if project.id == CANONICAL_3GB1_PROJECT_ID
        )
        legacy = next(project for project in projects if project.legacy_seed)
        assert canonical.seed is True
        assert legacy.seed is False
        assert legacy.id != canonical.id
        assert (
            manager.load_workflow(legacy.id)
            .nodes["n1"]
            .parameters["prefix"]
            == "user edit"
        )
        assert (
            manager.load_workflow(canonical.id)
            .nodes["n1"]
            .parameters["prefix"]
            == "shipped upgrade"
        )

    def test_ordinary_workflow_and_metadata_save_rejects_canonical(
        self,
        tmp_path: Path,
    ) -> None:
        workflow_path = tmp_path / "workflow.json"
        workflow_path.write_text(SAMPLE_WORKFLOW_JSON)

        from core import TypeRegistry, ModuleRegistry, discover_modules
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        manager = ProjectManager(
            root_dir=tmp_path / "projects",
            module_registry=module_registry,
        )
        canonical = manager.ensure_seed_project(workflow_path)
        assert canonical is not None

        with pytest.raises(ProtectedProjectError):
            manager.save(canonical.id, manager.load_workflow(canonical.id), UIState())

        reloaded = manager.load_meta(canonical.id)
        assert reloaded is not None
        assert reloaded.modified_at == canonical.modified_at

    def test_noncanonical_seed_claim_is_demoted_and_not_duplicated(
        self,
        tmp_path: Path,
    ) -> None:
        workflow_path = tmp_path / "workflow.json"
        workflow_path.write_text(SAMPLE_WORKFLOW_JSON)

        from core import TypeRegistry, ModuleRegistry, discover_modules
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        manager = ProjectManager(
            root_dir=tmp_path / "projects",
            module_registry=module_registry,
        )
        spoofed = manager.create("Old seed")
        spoofed_meta_path = manager.project_dir(spoofed.id) / "project.json"
        spoofed_meta = json.loads(spoofed_meta_path.read_text())
        spoofed_meta["seed"] = True
        spoofed_meta_path.write_text(json.dumps(spoofed_meta))

        manager.ensure_seed_project(workflow_path)
        manager.ensure_seed_project(workflow_path)

        projects = manager.list_projects()
        assert sum(project.seed for project in projects) == 1
        legacy = next(
            project for project in projects if project.id == spoofed.id
        )
        assert legacy.seed is False
        assert legacy.legacy_seed is True

    def test_failed_atomic_upgrade_leaves_previous_canonical_intact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workflow_path = tmp_path / "workflow.json"
        workflow_path.write_text(SAMPLE_WORKFLOW_JSON)

        from core import TypeRegistry, ModuleRegistry, discover_modules
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        manager = ProjectManager(
            root_dir=tmp_path / "projects",
            module_registry=module_registry,
        )
        original = manager.ensure_seed_project(workflow_path, version="1")
        assert original is not None

        workflow_path.write_text(
            SAMPLE_WORKFLOW_JSON.replace(
                '"parameters": {}',
                '"parameters": {"prefix": "upgrade"}',
            )
        )
        real_replace = os.replace

        def fail_stage_publish(source, destination):
            if (
                Path(source).name.startswith("canonical-stage-")
                and Path(destination).name == CANONICAL_3GB1_PROJECT_ID
            ):
                raise OSError("simulated publish failure")
            return real_replace(source, destination)

        monkeypatch.setattr("core.project.os.replace", fail_stage_publish)

        with pytest.raises(OSError, match="simulated publish failure"):
            manager.ensure_seed_project(workflow_path, version="2")

        restored = manager.load_meta(CANONICAL_3GB1_PROJECT_ID)
        assert restored is not None
        assert restored.seed_version == "1"
        assert (
            manager.load_workflow(CANONICAL_3GB1_PROJECT_ID)
            .nodes["n1"]
            .parameters
            == {}
        )

    def test_canonical_input_symlink_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "seed.pdb").write_text("END\n")
        (tmp_path / "pdbs").symlink_to(outside, target_is_directory=True)
        workflow_path = tmp_path / "workflow.json"
        workflow_path.write_text(
            """
            {
              "nodes": [
                {
                  "node_id": "import",
                  "module_id": "import.structure",
                  "parameters": {"file_path": "pdbs/seed.pdb"}
                }
              ],
              "edges": []
            }
            """
        )
        monkeypatch.chdir(tmp_path)

        from core import TypeRegistry, ModuleRegistry, discover_modules
        type_registry = TypeRegistry()
        module_registry = ModuleRegistry(type_registry)
        discover_modules(module_registry)
        manager = ProjectManager(
            root_dir=tmp_path / "projects",
            module_registry=module_registry,
        )

        with pytest.raises(CanonicalSeedError, match="Unsafe canonical input"):
            manager.ensure_seed_project(workflow_path)

        assert manager.list_projects() == []

    def test_canonical_project_id_is_independent_of_workflow_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path_v1 = Path(tmpdir) / "workflow-v1.json"
            wf_path_v2 = Path(tmpdir) / "workflow-v2.json"
            wf_path_v1.write_text(SAMPLE_WORKFLOW_JSON)
            wf_path_v2.write_text(
                SAMPLE_WORKFLOW_JSON.replace(
                    '"parameters": {}',
                    '"parameters": {"prefix": "upgraded"}',
                )
            )

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            # Two separate ProjectManager instances with different roots
            pm1 = ProjectManager(root_dir=str(Path(tmpdir) / "projects1"),
                                 module_registry=mr)
            pm2 = ProjectManager(root_dir=str(Path(tmpdir) / "projects2"),
                                 module_registry=mr)

            r1 = pm1.ensure_seed_project(str(wf_path_v1))
            r2 = pm2.ensure_seed_project(str(wf_path_v2))

            assert r1 is not None
            assert r2 is not None
            assert r1.id == CANONICAL_3GB1_PROJECT_ID
            assert r2.id == CANONICAL_3GB1_PROJECT_ID

    def test_missing_workflow_fails_visibly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)
            with pytest.raises(CanonicalSeedError, match="not found"):
                pm.ensure_seed_project(
                    str(Path(tmpdir) / "nonexistent.json")
                )

    def test_invalid_json_fails_visibly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "bad.json"
            wf_path.write_text("{invalid json")

            from core import TypeRegistry, ModuleRegistry, discover_modules
            tr = TypeRegistry()
            mr = ModuleRegistry(tr)
            discover_modules(mr)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"),
                                module_registry=mr)
            with pytest.raises(CanonicalSeedError, match="parse"):
                pm.ensure_seed_project(str(wf_path))

    def test_unknown_module_fails_visibly(self) -> None:
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
            with pytest.raises(
                CanonicalSeedError,
                match="module_unavailable",
            ):
                pm.ensure_seed_project(str(wf_path))

    def test_canonical_drift_fails_visibly_with_validation_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_path = Path(tmpdir) / "workflow.json"
            workflow_path.write_text(
                SAMPLE_WORKFLOW_JSON.replace(
                    '"module_id": "stub.echo"',
                    (
                        '"module_id": "stub.echo", '
                        '"module_version": "outdated"'
                    ),
                )
            )

            from core import TypeRegistry, ModuleRegistry, discover_modules
            type_registry = TypeRegistry()
            module_registry = ModuleRegistry(type_registry)
            discover_modules(module_registry)
            manager = ProjectManager(
                root_dir=Path(tmpdir) / "projects",
                module_registry=module_registry,
            )

            with pytest.raises(
                CanonicalSeedError,
                match="module_version_mismatch",
            ):
                manager.ensure_seed_project(workflow_path)

            assert manager.list_projects() == []

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

    def test_no_registry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wf_path = Path(tmpdir) / "workflow.json"
            wf_path.write_text(SAMPLE_WORKFLOW_JSON)

            pm = ProjectManager(root_dir=str(Path(tmpdir) / "projects"))
            with pytest.raises(
                CanonicalSeedError,
                match="requires a Module Registry",
            ):
                pm.ensure_seed_project(str(wf_path), name="No Registry")

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
