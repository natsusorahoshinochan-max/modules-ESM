"""Public storage-contract tests for contained project and run paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.project import ProjectManager
from core.run_context import RunContext
from core.server import app
from core.storage import StoragePathError
from datatypes import ProteinStructure, ScoreCollection
from modules.compute_sasa.module import ComputeSASAModule
from modules.export_structure.module import ExportStructureModule
from modules.simplefold_evaluate.module import SimpleFoldEvaluateModule


@pytest.mark.parametrize("project_id", ("../escape", "/tmp/escape"))
def test_project_manager_rejects_project_ids_outside_its_root(
    tmp_path: Path,
    project_id: str,
) -> None:
    project_root = tmp_path / "projects"
    manager = ProjectManager(root_dir=project_root)

    with pytest.raises(StoragePathError):
        manager.project_dir(project_id)

    assert list(tmp_path.iterdir()) == []


def test_configured_mutable_roots_are_isolated_by_project_and_run(
    tmp_path: Path,
) -> None:
    manager = ProjectManager(
        root_dir=tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = manager.create("Contained")

    first = manager.run_context(project.id, "run-a", "node-1")
    second = manager.run_context(project.id, "run-b", "node-1")

    assert Path(first.temp_dir) == (
        tmp_path / "runs" / project.id / "run-a" / "temp" / "node-1"
    )
    assert Path(first.output_dir) == (
        tmp_path / "outputs" / project.id / "run-a"
    )
    assert Path(first.log_dir) == (
        tmp_path / "runs" / project.id / "run-a" / "logs"
    )
    assert first.temp_dir != second.temp_dir
    assert first.output_dir != second.output_dir
    assert first.log_dir != second.log_dir


def test_default_run_paths_preserve_hybrid_project_storage(
    tmp_path: Path,
) -> None:
    manager = ProjectManager(root_dir=tmp_path / "projects")
    project = manager.create("Hybrid")

    context = manager.run_context(project.id, "run-a", "node-1")

    assert Path(context.project_dir) == tmp_path / "projects" / project.id
    assert Path(context.output_dir) == (
        tmp_path / "projects" / project.id / "outputs" / "run-a"
    )
    assert Path(context.temp_dir) == (
        tmp_path / "projects" / project.id
        / "runs" / "run-a" / "temp" / "node-1"
    )
    assert manager.input_path(project.id, "source.pdb") == (
        tmp_path / "projects" / project.id / "inputs" / "source.pdb"
    )


@pytest.mark.parametrize(
    ("operation", "unsafe_value"),
    (
        ("run", "../run"),
        ("node", "../../node"),
        ("upload", "../source.pdb"),
        ("artifact", "/tmp/result.pdb"),
        ("artifact", "../../result.pdb"),
    ),
)
def test_public_run_storage_rejects_unsafe_identifiers_and_paths(
    tmp_path: Path,
    operation: str,
    unsafe_value: str,
) -> None:
    manager = ProjectManager(root_dir=tmp_path / "projects")
    project = manager.create("Validation")

    with pytest.raises(StoragePathError):
        if operation == "run":
            manager.run_context(project.id, unsafe_value, "node-1")
        elif operation == "node":
            manager.run_context(project.id, "run-a", unsafe_value)
        elif operation == "upload":
            manager.input_path(project.id, unsafe_value)
        else:
            manager.output_path(project.id, "run-a", unsafe_value)


def test_direct_run_context_uses_run_scoped_hybrid_paths(
    tmp_path: Path,
) -> None:
    context = RunContext(
        project_dir=str(tmp_path / "project"),
        node_id="node-1",
        run_id="run-a",
    )

    assert Path(context.temp_dir) == (
        tmp_path / "project" / "runs" / "run-a" / "temp" / "node-1"
    )
    assert Path(context.output_dir) == (
        tmp_path / "project" / "outputs" / "run-a"
    )
    assert Path(context.log_dir) == (
        tmp_path / "project" / "runs" / "run-a" / "logs"
    )


@pytest.mark.parametrize(
    "payload",
    (
        {
            "project_id": "../outside",
            "nodes": [
                {
                    "node_id": "node-1",
                    "module_id": "stub.echo",
                    "module_version": "1.0.0",
                },
            ],
            "edges": [],
        },
        {
            "project_id": "ephemeral-safe",
            "nodes": [
                {
                    "node_id": "../../outside",
                    "module_id": "stub.echo",
                    "module_version": "1.0.0",
                },
            ],
            "edges": [],
        },
    ),
)
def test_execute_api_rejects_path_identifiers_without_external_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
) -> None:
    project_root = tmp_path / "projects"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))

    with TestClient(app) as client:
        response = client.post("/api/execute", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "invalid_storage_path"
    assert not (tmp_path / "outside").exists()


def test_upload_api_rejects_traversal_without_writing_external_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))

    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"name": "Upload containment"},
        ).json()["id"]
        response = client.post(
            f"/api/projects/{project_id}/inputs",
            files={"file": ("../outside.pdb", b"ATOM\n", "chemical/x-pdb")},
        )

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "uploaded_name"
    assert not (tmp_path / "outside.pdb").exists()


def test_exported_artifacts_with_the_same_name_are_isolated_by_run(
    tmp_path: Path,
) -> None:
    module = ExportStructureModule()
    structure = ProteinStructure(pdb_string="END\n")
    first_context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )
    second_context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-b",
    )

    first = module.run(
        {"structure": structure},
        {"filename": "result.pdb"},
        first_context,
    )
    second = module.run(
        {"structure": structure},
        {"filename": "result.pdb"},
        second_context,
    )

    assert Path(first["file_path"]) == (
        tmp_path / "project" / "outputs" / "run-a" / "result.pdb"
    )
    assert Path(second["file_path"]) == (
        tmp_path / "project" / "outputs" / "run-b" / "result.pdb"
    )
    assert first["file_path"] != second["file_path"]


@pytest.mark.parametrize("artifact_name", ("../outside.pdb", "/tmp/outside.pdb"))
def test_export_module_rejects_artifact_escape_without_external_write(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    module = ExportStructureModule()
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )

    with pytest.raises(StoragePathError):
        module.run(
            {"structure": ProteinStructure(pdb_string="END\n")},
            {"filename": artifact_name},
            context,
        )

    assert not (tmp_path / "outside.pdb").exists()


def test_project_storage_rejects_existing_symlink_escape(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects"
    manager = ProjectManager(root_dir=project_root)
    project = manager.create("Symlink containment")
    outside = tmp_path / "outside"
    outside.mkdir()
    inputs_dir = project_root / project.id / "inputs"
    inputs_dir.rmdir()
    inputs_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(StoragePathError):
        manager.input_path(project.id, "source.pdb")

    assert list(outside.iterdir()) == []


def test_download_api_reads_valid_run_scoped_hybrid_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "projects"
    output_root = tmp_path / "outputs"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))

    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"name": "Hybrid output"},
        ).json()["id"]
        artifact = output_root / project_id / "run-a" / "result.pdb"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("END\n")

        response = client.get(
            f"/api/projects/{project_id}/outputs/run-a/result.pdb"
        )

    assert response.status_code == 200
    assert response.text == "END\n"


def test_subprocess_temporary_file_uses_run_scoped_node_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "sasa",
        run_id="run-a",
    )
    observed: dict[str, Path] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        observed["input_path"] = Path(command[1])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("modules.compute_sasa.module.subprocess.run", fake_run)

    ComputeSASAModule().run(
        {"structure": ProteinStructure(pdb_string="END\n")},
        {},
        context,
    )

    assert observed["input_path"].parent == Path(context.temp_dir)


def test_provider_mutable_work_uses_run_scoped_node_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "simplefold",
        run_id="run-a",
    )
    observed: dict[str, str] = {}

    def fake_evaluate_structure(**kwargs: object) -> ScoreCollection:
        observed["project_dir"] = str(kwargs["project_dir"])
        return ScoreCollection(collection_id="scores", entries=[])

    monkeypatch.setattr(
        "modules.simplefold_adapter.evaluate_structure",
        fake_evaluate_structure,
    )

    SimpleFoldEvaluateModule().run(
        {"structure": ProteinStructure(pdb_string="END\n")},
        {},
        context,
    )

    assert observed["project_dir"] == context.temp_dir
