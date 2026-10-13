"""Portable example installation preserves real production-owner evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from core.catalog.builder import build_frozen_catalog
from core.catalog.model import FrozenCatalog
from core.execution.environment import admit_environment_configuration
from core.execution.ledger import Ledger
from core.execution.ledger.store import FilesystemLedgerStore
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.execution.runtime import V2RunService
from core.project.manager import WEBUI_3GB1_PROJECT_ID, ProjectManager, ProtectedProjectError
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import WorkflowDocument
from protein_workbench_public.bootstrap import module_registrations
from protein_workbench_public.example_results import export_example_results, install_example_results
from protein_workbench_public.workflow_codec import decode_workflow_document


PROJECT = WEBUI_3GB1_PROJECT_ID


def _projects(root: Path) -> ProjectManager:
    return ProjectManager(root / "projects", output_root=root / "objects-store", cache_root=root / "cache", run_root=root / "ledger-store")


def _runtime(projects: ProjectManager, catalog: FrozenCatalog, authoring: WorkflowAuthoringService) -> V2RunService:
    results = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
    return V2RunService(
        projects, catalog, authoring,
        NodeAttemptFactory(projects, admit_environment_configuration(catalog, {}), results),
        results,
    )


@dataclass
class Example:
    projects: ProjectManager
    catalog: FrozenCatalog
    authoring: WorkflowAuthoringService
    workflow: WorkflowDocument
    runtime: V2RunService
    run_id: str
    archive: Path


@pytest.fixture
def example(tmp_path: Path) -> Example:
    """Use real provider-free Nodes to test transport, not fake Provider results."""
    catalog = build_frozen_catalog(module_registrations())
    projects = _projects(tmp_path / "original")
    authoring = WorkflowAuthoringService(projects, catalog)
    sequence = tmp_path / "tiny.fasta"
    sequence.write_text(">input\nACD\n", encoding="utf-8")
    workflow = decode_workflow_document({
        "schema_version": "2.1.0", "workflow_id": PROJECT,
        "nodes": [
            {"node_id": "import", "node_type_id": "protein_io.import_sequence", "binding_id": "protein_io.import_sequence.direct", "node_parameters": {"project_input_ref": "tiny.fasta"}, "binding_parameters": {}},
            {"node_id": "author", "node_type_id": "prompt_authoring.author", "binding_id": "prompt_authoring.author.direct", "node_parameters": {"document": {"chains": [{"chain_id": "A", "length": 3}]}}, "binding_parameters": {}},
            {"node_id": "export", "node_type_id": "protein_io.export_sequence", "binding_id": "protein_io.export_sequence.direct", "node_parameters": {}, "binding_parameters": {}},
        ],
        "edges": [
            {"source_node_id": "import", "source_port": "sequence", "target_node_id": "author", "target_port": "sequence_source"},
            {"source_node_id": "import", "source_port": "sequence", "target_node_id": "export", "target_port": "sequence"},
        ],
        "observation_selectors": [], "selection_objectives": [],
    })
    commit = authoring.install_webui_example_commit(workflow=workflow, input_sources={"tiny.fasta": sequence})
    assert commit is not None
    runtime = _runtime(projects, catalog, authoring)
    receipt = runtime.start(PROJECT, workflow_commit_id=commit.workflow_commit_id, client_request_id="resource-test")
    run_id = receipt["run_id"]
    assert runtime.projection(PROJECT, run_id).status == "succeeded"
    archive = tmp_path / "example.zip"
    export_example_results(
        projects=projects, authoring=authoring,
        results=ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects)),
        run_id=run_id, destination=archive, expected_workflow=workflow,
    )
    return Example(projects, catalog, authoring, workflow, runtime, run_id, archive)


def test_round_trip_preserves_original_commit_ledger_objects_and_read_only_copy(example: Example, tmp_path: Path) -> None:
    target = _projects(tmp_path / "different-root")
    authoring = WorkflowAuthoringService(target, example.catalog)
    installed = install_example_results(resource=example.archive, projects=target, authoring=authoring)
    assert installed == example.run_id
    assert authoring.load_active_commit(PROJECT) == example.authoring.load_active_commit(PROJECT)
    assert authoring.webui_example_records() == example.authoring.webui_example_records()
    ledger_store = FilesystemLedgerStore()
    assert ledger_store.read_transactions(root=target.run_storage_root(PROJECT), relative_parts=(installed, "ledger")) == ledger_store.read_transactions(root=example.projects.run_storage_root(PROJECT), relative_parts=(installed, "ledger"))
    restarted = _runtime(target, example.catalog, WorkflowAuthoringService(target, example.catalog))
    projection = restarted.projection(PROJECT, installed)
    assert projection == example.runtime.projection(PROJECT, example.run_id)
    assert target.latest_run_id(PROJECT) == installed
    for publication in projection.publications:
        for output in publication.outputs:
            for index in range(output.value_count):
                assert restarted.typed_value(PROJECT, installed, publication.node_id, output.output_port, index) == example.runtime.typed_value(PROJECT, installed, publication.node_id, output.output_port, index)
        for artifact in publication.artifacts:
            assert restarted.artifact(PROJECT, installed, artifact.artifact_reference) == example.runtime.artifact(PROJECT, installed, artifact.artifact_reference)
    with pytest.raises(ProtectedProjectError):
        target.publish_input(PROJECT, "other", b"ACD", filename="other.fasta")
    copied = authoring.copy_project(PROJECT, name="Personal edit")
    assert copied.reference_results_project_id == PROJECT
    assert target.stored_run_ids(copied.id) == ()
    assert target.latest_run_id(PROJECT) == example.run_id
    assert not target.result_cache_storage_root(PROJECT).exists()
    assert install_example_results(resource=example.archive, projects=target, authoring=authoring) == installed


def test_resource_is_reproducible_and_manifest_has_no_generation_root(example: Example, tmp_path: Path) -> None:
    second = tmp_path / "same.zip"
    report = export_example_results(
        projects=example.projects, authoring=example.authoring,
        results=ResultStore(ProjectObjectStore(example.projects), ProjectReplayIndex(example.projects)),
        run_id=example.run_id, destination=second, expected_workflow=example.workflow,
    )
    assert second.read_bytes() == example.archive.read_bytes()
    assert report["compressed_bytes"] == second.stat().st_size
    with ZipFile(second) as archive:
        assert all(not Path(name).is_absolute() for name in archive.namelist())
        assert str(tmp_path).encode() not in archive.read("manifest.json")
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["workflow_commit_id"] == example.authoring.load_active_commit(PROJECT).workflow_commit_id
        assert len(manifest["objects"]) == report["object_count"]
        assert report["uncompressed_bytes"] == sum(info.file_size for info in archive.infolist())


def test_final_run_publication_failure_can_retry_without_partial_evidence(example: Example, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _projects(tmp_path / "interrupted-target")
    authoring = WorkflowAuthoringService(target, example.catalog)
    destination = target.run_storage_directory(PROJECT, example.run_id)
    rename = Path.rename

    def fail_publication(path: Path, target_path: Path) -> Path:
        if target_path == destination:
            raise OSError("simulated interrupted Run directory publication")
        return rename(path, target_path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_publication)
        with pytest.raises(OSError, match="interrupted Run"):
            install_example_results(resource=example.archive, projects=target, authoring=authoring)
    assert target.stored_run_ids(PROJECT) == ()
    assert install_example_results(resource=example.archive, projects=target, authoring=authoring) == example.run_id
    assert Ledger.load(target, PROJECT, example.run_id) is not None


def test_conflicting_original_commit_is_not_replaced(example: Example, tmp_path: Path) -> None:
    target = _projects(tmp_path / "conflicting-target")
    authoring = WorkflowAuthoringService(target, example.catalog)
    sequence = tmp_path / "tiny.fasta"
    sequence.write_text(">input\nACD\n", encoding="utf-8")
    original = authoring.install_webui_example_commit(workflow=example.workflow, input_sources={"tiny.fasta": sequence})
    assert original is not None
    assert original.workflow_commit_id != example.authoring.load_active_commit(PROJECT).workflow_commit_id
    with pytest.raises(ValueError, match="authoring records differ"):
        install_example_results(resource=example.archive, projects=target, authoring=authoring)
    assert authoring.load_active_commit(PROJECT) == original
    assert target.stored_run_ids(PROJECT) == ()


def test_cache_replayed_run_cannot_be_presented_as_fresh_example(example: Example, tmp_path: Path) -> None:
    commit = example.authoring.load_active_commit(PROJECT)
    replayed = example.runtime.start(PROJECT, workflow_commit_id=commit.workflow_commit_id, client_request_id="cache-replayed-resource")
    with pytest.raises(ValueError, match="without cache replay"):
        export_example_results(
            projects=example.projects, authoring=example.authoring,
            results=ResultStore(ProjectObjectStore(example.projects), ProjectReplayIndex(example.projects)),
            run_id=replayed["run_id"], destination=tmp_path / "replayed.zip", expected_workflow=example.workflow,
        )
    assert not (tmp_path / "replayed.zip").exists()
