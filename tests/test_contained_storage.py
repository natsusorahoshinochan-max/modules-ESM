"""Public storage-contract tests for contained project and run paths."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import pickle
import shutil
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import ModuleRegistry, TypeRegistry, discover_modules
from core.executor import Executor
from core.project import ProjectManager
from core.run_context import RunContext
from core.server import app
import core.storage as storage
from core.storage import StoragePathError, write_private_new_file
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
    ScoreCollection,
)
from modules.compute_sasa.module import ComputeSASAModule
from modules.export_structure.module import ExportStructureModule
from modules.import_sequence.module import ImportSequenceModule
from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
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


def test_private_new_file_is_complete_before_atomic_noreplace_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[bytes] = []
    original_publish = storage._rename_private_noreplace

    def observe_publish(
        directory_fd: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        assert destination_name == "fact.json"
        if not observed:
            assert not (tmp_path / "ledger" / destination_name).exists()
        observed.append(
            (tmp_path / "ledger" / source_name).read_bytes()
        )
        original_publish(directory_fd, source_name, destination_name)

    monkeypatch.setattr(
        storage,
        "_rename_private_noreplace",
        observe_publish,
    )
    destination = write_private_new_file(
        tmp_path,
        ("ledger", "fact.json"),
        b'{"complete":true}',
        field="test_fact",
    )

    assert observed == [b'{"complete":true}']
    assert destination.read_bytes() == b'{"complete":true}'
    with pytest.raises(FileExistsError):
        write_private_new_file(
            tmp_path,
            ("ledger", "fact.json"),
            b"replacement",
            field="test_fact",
        )
    assert observed == [b'{"complete":true}', b"replacement"]
    assert destination.read_bytes() == b'{"complete":true}'
    assert list((tmp_path / "ledger").glob("*.pending")) == []


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


def test_upload_api_returns_hybrid_relative_input_reference(
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
            json={"name": "Hybrid input"},
        ).json()["id"]
        response = client.post(
            f"/api/projects/{project_id}/inputs",
            files={"file": ("source.fasta", b">safe\nAGS\n", "text/plain")},
        )
        execution = client.post(
            "/api/execute",
            json={
                "project_id": project_id,
                "nodes": [
                    {
                        "node_id": "reader",
                        "module_id": "import.sequence",
                        "module_version": "1.0.0",
                        "parameters": {"file_path": response.json()["path"]},
                    },
                ],
                "edges": [],
            },
        )

    assert response.json()["path"] == "inputs/source.fasta"
    assert execution.status_code == 200


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


def test_export_module_refuses_existing_hardlink_before_writing(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.pdb"
    outside.write_text("ORIGINAL\n")
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )
    destination = (
        tmp_path / "project" / "outputs" / "run-a" / "result.pdb"
    )
    destination.parent.mkdir(parents=True)
    os.link(outside, destination)

    with pytest.raises((FileExistsError, StoragePathError)):
        ExportStructureModule().run(
            {"structure": ProteinStructure(pdb_string="REPLACEMENT\n")},
            {"filename": "result.pdb"},
            context,
        )

    assert outside.read_text() == "ORIGINAL\n"


def test_collection_export_rejects_oversized_count_before_first_write(
    tmp_path: Path,
) -> None:
    candidates = CandidateCollection(
        collection_id="too-many",
        item_type="protein.structure",
        items=[
            Candidate(
                candidate_id=f"candidate-{index}",
                data=ProteinStructure(pdb_string="END\n"),
            )
            for index in range(2049)
        ],
    )
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )

    with pytest.raises(ValueError, match="too many"):
        ExportStructureModule().run(
            {"structures": candidates},
            {"directory": "final"},
            context,
        )

    assert not Path(context.output_dir or "").exists()


def test_collection_export_removes_partial_files_when_later_create_fails(
    tmp_path: Path,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )
    output_dir = Path(context.output_dir or "")
    destination = output_dir / "final" / "candidate-2.pdb"
    destination.parent.mkdir(parents=True)
    destination.write_text("EXISTING\n")
    structures = CandidateCollection(
        collection_id="two",
        item_type="protein.structure",
        items=[
            Candidate(
                candidate_id=f"candidate-{index}",
                data=ProteinStructure(pdb_string=f"MODEL {index}\n"),
            )
            for index in (1, 2)
        ],
    )

    with pytest.raises(FileExistsError):
        ExportStructureModule().run(
            {"structures": structures},
            {"directory": "final"},
            context,
        )

    assert not (output_dir / "final" / "candidate-1.pdb").exists()
    assert destination.read_text() == "EXISTING\n"


def test_collection_export_rolls_back_when_manifest_batch_is_incomplete(
    tmp_path: Path,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "export",
        run_id="run-a",
    )
    context._manifest_store = SimpleNamespace(
        record_artifacts=lambda **kwargs: False,
    )
    structures = CandidateCollection(
        collection_id="one",
        item_type="protein.structure",
        items=[
            Candidate(
                candidate_id="candidate-1",
                data=ProteinStructure(pdb_string="MODEL 1\n"),
            )
        ],
    )

    with pytest.raises(RuntimeError, match="could not be recorded"):
        ExportStructureModule().run(
            {"structures": structures},
            {"directory": "final"},
            context,
        )

    assert not (
        Path(context.output_dir or "") / "final" / "candidate-1.pdb"
    ).exists()


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


def test_download_api_rejects_unmanifested_run_scoped_hybrid_output(
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

    assert response.status_code == 404
    assert response.json()["error"]["kind"] == "run_not_found"


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
        provider_working_dir = Path(str(kwargs["project_dir"]))
        observed["project_dir"] = str(provider_working_dir)
        assert provider_working_dir.is_dir()
        assert not provider_working_dir.is_symlink()
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

    provider_working_dir = Path(observed["project_dir"])
    assert provider_working_dir.parent == Path(str(context.temp_dir))
    assert not provider_working_dir.exists()
    assert not provider_working_dir.is_symlink()


def test_provider_mutable_work_rejects_symlinked_node_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "simplefold",
        run_id="run-a",
    )
    node_temp = Path(str(context.temp_dir))
    outside = tmp_path / "outside"
    outside.mkdir()
    node_temp.parent.mkdir(parents=True)
    node_temp.symlink_to(outside, target_is_directory=True)
    provider = pytest.fail
    monkeypatch.setattr(
        "modules.simplefold_adapter.evaluate_structure",
        provider,
    )

    with pytest.raises(StoragePathError, match="temporary_directory"):
        SimpleFoldEvaluateModule().run(
            {"structure": ProteinStructure(pdb_string="END\n")},
            {},
            context,
        )

    assert list(outside.iterdir()) == []


def test_provider_mutable_work_removes_invocation_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "simplefold",
        run_id="run-a",
    )
    observed: dict[str, Path] = {}

    def fail_evaluate_structure(**kwargs: object) -> ScoreCollection:
        working_dir = Path(str(kwargs["project_dir"]))
        observed["working_dir"] = working_dir
        (working_dir / "partial-provider-state").write_text("partial")
        raise RuntimeError("provider failed")

    monkeypatch.setattr(
        "modules.simplefold_adapter.evaluate_structure",
        fail_evaluate_structure,
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        SimpleFoldEvaluateModule().run(
            {"structure": ProteinStructure(pdb_string="END\n")},
            {},
            context,
        )

    assert not observed["working_dir"].exists()


def test_provider_failure_is_not_masked_by_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = RunContext(
        str(tmp_path / "project"),
        "simplefold",
        run_id="run-a",
    )
    observed: dict[str, Path] = {}
    real_rmtree = shutil.rmtree

    def fail_evaluate_structure(**kwargs: object) -> ScoreCollection:
        observed["working_dir"] = Path(str(kwargs["project_dir"]))
        raise ValueError("provider failed")

    def fail_cleanup(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise PermissionError("cleanup failed")

    setattr(fail_cleanup, "avoids_symlink_attacks", True)
    monkeypatch.setattr(
        "modules.simplefold_adapter.evaluate_structure",
        fail_evaluate_structure,
    )
    monkeypatch.setattr("core.run_context.shutil.rmtree", fail_cleanup)

    with pytest.raises(ValueError, match="provider failed") as raised:
        SimpleFoldEvaluateModule().run(
            {"structure": ProteinStructure(pdb_string="END\n")},
            {},
            context,
        )

    assert any(
        "cleanup also failed: PermissionError" in note
        for note in (raised.value.__notes__ or [])
    )
    real_rmtree(observed["working_dir"])


def test_execute_api_rejects_import_path_outside_project_inputs(
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
    payload = {
        "nodes": [
            {
                "node_id": "reader",
                "module_id": "import.sequence",
                "module_version": "1.0.0",
                "parameters": {"file_path": "/etc/hosts"},
            },
        ],
        "edges": [],
    }

    with TestClient(app) as client:
        payload["project_id"] = client.post(
            "/api/projects",
            json={"name": "Contained import"},
        ).json()["id"]
        response = client.post("/api/execute", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "input_path"
    assert "run_id" not in response.json()


def test_import_module_accepts_only_current_project_input_paths(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    uploaded = project_dir / "inputs" / "sequence.fasta"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_text(">safe\nAGS\n")
    context = RunContext(str(project_dir), "reader", run_id="run-a")
    module = ImportSequenceModule()

    result = module.run({}, {"file_path": str(uploaded)}, context)
    assert result["sequence"].sequence == "AGS"

    with pytest.raises(StoragePathError):
        module.run({}, {"file_path": "/etc/hosts"}, context)


def test_cache_node_namespaces_do_not_overlap_by_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROJECT_ROOT",
        str(tmp_path / "projects"),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))

    with TestClient(app) as client:
        project_id = client.post(
            "/api/projects",
            json={"name": "Cache containment"},
        ).json()["id"]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={
                "nodes": [
                    {
                        "node_id": node_id,
                        "module_id": "stub.echo",
                        "module_version": "1.0.0",
                    }
                    for node_id in ("a", "a_b")
                ],
                "edges": [],
            },
        ).status_code == 200
        first = cache_root / project_id / "a" / f"{'1' * 32}.pkl"
        second = cache_root / project_id / "a_b" / f"{'2' * 32}.pkl"
        first.parent.mkdir(parents=True)
        second.parent.mkdir(parents=True)
        first.write_bytes(b"first")
        second.write_bytes(b"second")

        response = client.delete(f"/api/projects/{project_id}/cache/a")

    assert response.json() == {
        "project_id": project_id,
        "node_id": "a",
        "status": "cleared",
        "removed": 1,
    }
    assert not first.exists()
    assert second.read_bytes() == b"second"


def test_concurrent_cache_writes_publish_one_complete_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "cache" / "node" / "key.pkl"
    cache_path.parent.mkdir(parents=True)
    executor = Executor()
    first_half_written = threading.Event()
    second_write_finished = threading.Event()

    def interleaved_dump(outputs: dict, destination: object) -> None:
        payload = pickle.dumps(outputs)
        if outputs["run"] == "first":
            split = len(payload) // 2
            destination.write(payload[:split])
            destination.flush()
            first_half_written.set()
            assert second_write_finished.wait(timeout=2)
            destination.write(payload[split:])
            destination.flush()
            return
        assert first_half_written.wait(timeout=2)
        destination.write(payload)
        destination.flush()
        second_write_finished.set()

    monkeypatch.setattr("core.executor.pickle.dump", interleaved_dump)
    first = {"run": "first"}
    second = {"run": "second", "payload": "x" * 10_000}

    with ThreadPoolExecutor(max_workers=2) as pool:
        writes = [
            pool.submit(executor._save_to_cache, cache_path, outputs)
            for outputs in (first, second)
        ]
        for write in writes:
            write.result(timeout=3)

    assert executor._load_from_cache(cache_path) in (first, second)
    assert list(cache_path.parent.iterdir()) == [cache_path]


def test_run_namespace_rejects_symlink_alias_to_another_run(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs"
    manager = ProjectManager(
        root_dir=tmp_path / "projects",
        output_root=output_root,
    )
    project = manager.create("Run alias")
    second_run = output_root / project.id / "run-b"
    second_run.mkdir(parents=True)
    (output_root / project.id / "run-a").symlink_to(
        second_run,
        target_is_directory=True,
    )

    with pytest.raises(StoragePathError):
        manager.output_dir(project.id, "run-a")


def test_proteinmpnn_provider_temp_is_run_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    def fake_design_sequences(
        **kwargs: object,
    ) -> tuple[list[ProteinSequence], list[float]]:
        observed["temp_dir"] = str(kwargs["temp_dir"])
        return [ProteinSequence(sequence="A")], [-1.0]

    monkeypatch.setattr(
        "modules.proteinmpnn.module_design.design_sequences",
        fake_design_sequences,
    )
    context = RunContext(
        str(tmp_path / "project"),
        "mpnn",
        run_id="run-a",
    )

    ProteinMPNNDesignModule().run(
        {"structure": ProteinStructure(pdb_string="END\n")},
        {},
        context,
    )

    assert observed["temp_dir"] == context.temp_dir


def test_seed_project_provisions_relative_imports_under_project_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "pdbs" / "seed.pdb"
    source.parent.mkdir()
    source.write_text("END\n")
    workflow_path = tmp_path / "seed-workflow.json"
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
    type_registry = TypeRegistry()
    module_registry = ModuleRegistry(type_registry)
    discover_modules(module_registry)
    manager = ProjectManager(
        root_dir=tmp_path / "projects",
        module_registry=module_registry,
    )

    project = manager.ensure_seed_project(workflow_path)

    assert project is not None
    provisioned = (
        tmp_path / "projects" / project.id / "inputs" / "pdbs" / "seed.pdb"
    )
    assert provisioned.read_text() == "END\n"
    loaded = manager.load_workflow(project.id)
    assert loaded.nodes["import"].parameters["file_path"] == "pdbs/seed.pdb"
