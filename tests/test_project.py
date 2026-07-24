"""Tests for ProjectManager persistence and missing-module handling."""

import json
import tempfile
from pathlib import Path

from core import ModuleRegistry, ProjectManager, TypeRegistry, Workflow, WorkflowEdge, WorkflowNode, discover_modules


class TestProjectManager:
    def test_create_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp)
            meta = pm.create("Test Project")
            assert meta.name == "Test Project"
            assert meta.id
            project_dir = Path(tmp) / meta.id
            assert project_dir.is_dir()
            assert (project_dir / "project.json").exists()
            assert (project_dir / "workflow.json").exists()
            assert (project_dir / "ui.json").exists()
            assert (project_dir / "inputs").is_dir()
            assert (project_dir / "outputs").is_dir()

    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp)
            meta = pm.create("Round Trip")

            # Build workflow
            wf = Workflow()
            wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0", {"repeat": 3}))
            wf.add_node(WorkflowNode("b", "stub.echo", "1.0.0", {"prefix": "X:"}))
            wf.add_edge(WorkflowEdge("a", "text", "b", "text"))

            from core.project import UIState
            ui = UIState(
                node_positions={"a": {"x": 100, "y": 200}, "b": {"x": 400, "y": 200}},
                canvas_zoom=1.5,
            )

            pm.save(meta.id, wf, ui)

            # Load and verify
            loaded_wf = pm.load_workflow(meta.id)
            assert len(loaded_wf.nodes) == 2
            assert loaded_wf.nodes["a"].parameters == {"repeat": 3}
            assert loaded_wf.nodes["b"].parameters == {"prefix": "X:"}
            assert len(loaded_wf.edges) == 1
            assert loaded_wf.edges[0].source_node_id == "a"
            assert loaded_wf.edges[0].target_node_id == "b"

            loaded_ui = pm.load_ui(meta.id)
            assert loaded_ui.node_positions == {"a": {"x": 100, "y": 200}, "b": {"x": 400, "y": 200}}
            assert loaded_ui.canvas_zoom == 1.5

    def test_save_preserves_all_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp)
            meta = pm.create("Params")
            wf = Workflow()
            wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0", {"repeat": 5, "prefix": "> "}))
            from core.project import UIState
            pm.save(meta.id, wf, UIState())

            loaded = pm.load_workflow(meta.id)
            assert loaded.nodes["n1"].parameters == {"repeat": 5, "prefix": "> "}

    def test_list_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp)
            pm.create("A")
            pm.create("B")
            projects = pm.list_projects()
            assert len(projects) == 2
            names = {p.name for p in projects}
            assert names == {"A", "B"}

    def test_load_nonexistent_project_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp)
            assert pm.load_meta("nonexistent") is None


class TestMissingUI:
    def test_missing_ui_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp)
            meta = pm.create("MissingUI")
            # Delete ui.json
            (Path(tmp) / meta.id / "ui.json").unlink()

            ui = pm.load_ui(meta.id)
            assert ui.node_positions == {}
            assert ui.canvas_zoom == 1.0

    def test_corrupt_ui_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp)
            meta = pm.create("CorruptUI")
            (Path(tmp) / meta.id / "ui.json").write_text("not valid json")

            ui = pm.load_ui(meta.id)
            assert ui.canvas_zoom == 1.0  # default

    def test_workflow_loads_without_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp)
            meta = pm.create("WFOnly")
            wf = Workflow()
            wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0"))
            from core.project import UIState
            pm.save(meta.id, wf, UIState())
            # Delete ui.json
            (Path(tmp) / meta.id / "ui.json").unlink()

            loaded_wf = pm.load_workflow(meta.id)
            assert "n1" in loaded_wf.nodes
            assert loaded_wf.nodes["n1"].module_id == "stub.echo"


class TestMissingModules:
    def setup_method(self) -> None:
        self.tr = TypeRegistry()
        self.mr = ModuleRegistry(self.tr)
        discover_modules(self.mr)

    def test_missing_module_creates_unavailable_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp, module_registry=self.mr)

            # Save workflow that references a missing module
            wf = Workflow()
            wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0"))
            wf.add_node(WorkflowNode("n2", "nonexistent.module", "1.0.0", {"param": 42}))
            from core.project import UIState
            meta = pm.create("MissingMod")
            pm.save(meta.id, wf, UIState())

            # Load — missing module should be marked unavailable
            loaded = pm.load_workflow(meta.id)
            assert loaded.nodes["n1"].module_id == "stub.echo"
            assert getattr(loaded.nodes["n1"], "available", True) is True
            assert loaded.nodes["n2"].module_id == "nonexistent.module"
            assert getattr(loaded.nodes["n2"], "available", True) is False
            assert loaded.nodes["n2"].parameters == {"param": 42}

    def test_missing_module_rest_of_workflow_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp, module_registry=self.mr)

            wf = Workflow()
            wf.add_node(WorkflowNode("a", "stub.echo", "1.0.0"))
            wf.add_node(WorkflowNode("b", "nonexistent.module", "1.0.0"))
            wf.add_node(WorkflowNode("c", "stub.echo", "1.0.0"))
            wf.add_edge(WorkflowEdge("a", "text", "b", "text"))
            wf.add_edge(WorkflowEdge("b", "text", "c", "text"))
            from core.project import UIState
            meta = pm.create("IntactTest")
            pm.save(meta.id, wf, UIState())

            loaded = pm.load_workflow(meta.id)
            assert len(loaded.nodes) == 3
            assert len(loaded.edges) == 2
            # a and c should be available, b unavailable
            assert getattr(loaded.nodes["a"], "available", True) is True
            assert getattr(loaded.nodes["b"], "available", True) is False
            assert getattr(loaded.nodes["c"], "available", True) is True

    def test_installed_module_restores_to_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm1 = ProjectManager(root_dir=tmp)  # no registry → all modules "missing"
            wf = Workflow()
            wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0"))
            from core.project import UIState
            meta = pm1.create("Restore")
            pm1.save(meta.id, wf, UIState())

            # Load without registry → unavailable
            loaded1 = pm1.load_workflow(meta.id)
            assert getattr(loaded1.nodes["n1"], "available", True) is False

            # Load with registry → available
            pm2 = ProjectManager(root_dir=tmp, module_registry=self.mr)
            loaded2 = pm2.load_workflow(meta.id)
            assert getattr(loaded2.nodes["n1"], "available", True) is True

    def test_workflow_ui_independence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(root_dir=tmp, module_registry=self.mr)
            wf = Workflow()
            wf.add_node(WorkflowNode("n1", "stub.echo", "1.0.0"))
            from core.project import UIState
            ui = UIState(node_positions={"n1": {"x": 42, "y": 99}})
            meta = pm.create("Independence")
            pm.save(meta.id, wf, ui)

            # Change workflow, reload UI — UI should be unchanged
            wf2 = Workflow()
            wf2.add_node(WorkflowNode("n2", "stub.echo", "1.0.0"))
            pm.save(meta.id, wf2, ui)  # reuse same UI

            loaded_ui = pm.load_ui(meta.id)
            assert loaded_ui.node_positions == {"n1": {"x": 42, "y": 99}}

            loaded_wf = pm.load_workflow(meta.id)
            assert "n2" in loaded_wf.nodes
