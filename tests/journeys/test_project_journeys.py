"""Project persistence journeys through the real public application boundary.

These scenarios own copy and incomplete-project behavior. They do not claim
that upload is historical-result adoption or that an injected Catalog proves
application-level module installation.
"""

from __future__ import annotations

import base64
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.catalog.builder import build_frozen_catalog
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
from tests.support.application import create_application
from tests.support.public_runs import PublicRunClient


def _workflow(project_id: str, input_ref: str) -> dict[str, Any]:
    return {
        "schema_version": "2.1.0",
        "workflow_id": project_id,
        "nodes": [{
            "node_id": "import",
            "node_type_id": "protein_io.import_sequence",
            "binding_id": "protein_io.import_sequence.direct",
            "node_parameters": {"project_input_ref": input_ref},
            "binding_parameters": {},
        }],
        "edges": [],
    }


def test_copy_of_executed_project_is_unrun_and_survives_source_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    catalog = build_frozen_catalog((PROTEIN_IO_PACKAGE,))
    app = create_application(frozen_catalog_override=catalog)
    with TestClient(app) as http:
        client = PublicRunClient(http)
        created = http.post("/api/v2/projects", json={"name": "Executed source"})
        assert created.status_code == 201, created.text
        source_id = created.json()["id"]
        prefix = f"/api/v2/projects/{source_id}"
        content = b">source\nACDE\n"
        published = http.post(f"{prefix}/inputs", json={
            "filename": "source.fasta",
            "content_base64": base64.b64encode(content).decode("ascii"),
        })
        assert published.status_code == 201, published.text
        input_ref = published.json()["project_input_ref"]
        workflow = _workflow(source_id, input_ref)
        layout = {"positions": {"import": {"x": 37, "y": 84}}, "zoom": 1.25}
        saved = http.put(f"{prefix}/workspace", json={"workflow": workflow, "ui_state": layout})
        assert saved.status_code == 200, saved.text
        commit = client.commit_workflow(source_id, workflow)
        receipt = client.start_run(source_id, commit["workflow_commit_id"], request_id="source-run")
        source_run = client.wait_terminal(source_id, receipt["run_id"])
        assert source_run["status"] == "succeeded"
        assert source_run["outputs"]
        expected_values = [
            client.typed_output_bytes(source_id, receipt["run_id"], output, index)
            for output in source_run["outputs"]
            for index in range(output["value_count"])
        ]
        source_workspace = http.get(f"{prefix}/workspace").json()
        copied = http.post(f"{prefix}:duplicate", json={"name": "Independent copy"})
        assert copied.status_code == 201, copied.text
        target_id = copied.json()["id"]
        target_prefix = f"/api/v2/projects/{target_id}"
        target_workspace = http.get(f"{target_prefix}/workspace").json()
        assert target_workspace["ui_state"] == layout
        target_workflow = target_workspace["draft"]["workflow"]
        assert target_workflow["workflow_id"] == target_id
        assert target_workflow["nodes"] == source_workspace["draft"]["workflow"]["nodes"]
        assert target_workflow["edges"] == source_workspace["draft"]["workflow"]["edges"]
        assert app.state.project_manager.stored_run_ids(target_id) == ()
        assert not app.state.project_manager.result_cache_storage_root(target_id).exists()
        assert http.get(f"{target_prefix}/runs/{receipt['run_id']}").status_code == 404
        assert http.get(f"{prefix}/workspace").json() == source_workspace
        assert http.get(f"{prefix}/runs/{receipt['run_id']}").json() == source_run
        assert http.post(f"{prefix}:trash").status_code == 200
        assert http.delete(prefix).status_code == 200

    restarted = create_application(frozen_catalog_override=catalog)
    with TestClient(restarted) as http:
        client = PublicRunClient(http)
        reopened = http.get(f"{target_prefix}/workspace")
        assert reopened.status_code == 200, reopened.text
        assert reopened.json() == target_workspace
        descriptor, retained = restarted.state.project_manager.read_input(target_id, input_ref)
        assert descriptor.filename == "source.fasta"
        assert retained == content
        commit = client.commit_workflow(target_id, target_workflow)
        receipt = client.start_run(target_id, commit["workflow_commit_id"], request_id="copy-run")
        run = client.wait_terminal(target_id, receipt["run_id"])
        assert run["status"] == "succeeded"
        actual_values = [
            client.typed_output_bytes(target_id, receipt["run_id"], output, index)
            for output in run["outputs"]
            for index in range(output["value_count"])
        ]
        assert actual_values == expected_values


def test_missing_module_project_is_preserved_until_catalog_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    catalog = build_frozen_catalog((PROTEIN_IO_PACKAGE,))
    with TestClient(create_application(frozen_catalog_override=catalog)) as http:
        created = http.post("/api/v2/projects", json={"name": "Missing module"})
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        prefix = f"/api/v2/projects/{project_id}"
        uploaded = http.post(f"{prefix}/inputs", json={
            "filename": "retained.fasta",
            "content_base64": base64.b64encode(b">retained\nACDE\n").decode("ascii"),
        })
        assert uploaded.status_code == 201, uploaded.text
        workflow = _workflow(project_id, uploaded.json()["project_input_ref"])
        layout = {"positions": {"import": {"x": 8, "y": 15}}}
        saved = http.put(f"{prefix}/workspace", json={"workflow": workflow, "ui_state": layout})
        assert saved.status_code == 200, saved.text
        snapshot = saved.json()

    missing_catalog = build_frozen_catalog(())
    with TestClient(create_application(frozen_catalog_override=missing_catalog)) as http:
        reopened = http.get(f"{prefix}/workspace")
        assert reopened.status_code == 200, reopened.text
        assert reopened.json() == snapshot
        rejected = http.post(f"{prefix}/workflow:commit", json={"workflow": workflow})
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["error"]["code"] == "compile_rejected"
        retained = http.get(f"{prefix}/workspace").json()
        # Commit explicitly saves before compilation; a rejected compilation
        # may add a revision, but must retain the authored content.
        assert retained["draft"]["workflow"] == snapshot["draft"]["workflow"]
        assert retained["ui_state"] == snapshot["ui_state"]
        assert http.app.state.project_manager.stored_run_ids(project_id) == ()
        assert http.get(f"{prefix}/inputs").json()["inputs"] == [uploaded.json()]

    with TestClient(create_application(frozen_catalog_override=catalog)) as http:
        restored = http.get(f"{prefix}/workspace").json()
        assert restored["draft"]["workflow"] == snapshot["draft"]["workflow"]
        assert restored["ui_state"] == snapshot["ui_state"]
        assert http.app.state.project_manager.stored_run_ids(project_id) == ()
        assert http.get(f"{prefix}/inputs").json()["inputs"] == [uploaded.json()]
        client = PublicRunClient(http)
        committed = client.commit_workflow(project_id, workflow)
        receipt = client.start_run(project_id, committed["workflow_commit_id"], request_id="module-restored")
        assert client.wait_terminal(project_id, receipt["run_id"])["status"] == "succeeded"


@pytest.mark.parametrize("operation", ["workspace", "rename", "input", "commit", "version"])
def test_running_project_rejects_mutation_but_remains_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    from tests.fixtures.run_scenarios import commit_one_node, direct_catalog

    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))

    def hold_execution(_resources: object) -> None:
        entered.set()
        if not release.wait(timeout=30):
            raise TimeoutError("project mutation scenario did not release execution")

    app = create_application(
        frozen_catalog_override=direct_catalog([], execution_action=hold_execution),
        v2_environment_configuration={"test.direct.local": {"credential": "credential-value"}},
    )
    with TestClient(app) as http:
        client = PublicRunClient(http)
        project_id, commit = commit_one_node(http)
        prefix = f"/api/v2/projects/{project_id}"
        saved = http.get(f"{prefix}/workspace").json()
        original_inputs = http.get(f"{prefix}/inputs").json()
        metadata = app.state.project_manager.require_meta(project_id)
        started = client.start_run(project_id, commit["workflow_commit_id"], request_id=f"active-{operation}")
        try:
            assert entered.wait(timeout=5), "operation did not reach its controlled execution seam"
            assert http.get(f"{prefix}/workspace").json() == saved
            projection = http.get(f"{prefix}/runs/{started['run_id']}")
            assert projection.status_code == 200
            assert projection.json()["status"] == "running"
            if operation == "workspace":
                response = http.put(f"{prefix}/workspace", json={"ui_state": {"zoom": 9}})
            elif operation == "rename":
                response = http.patch(prefix, json={"name": "Changed during computation"})
            elif operation == "commit":
                response = http.post(f"{prefix}/workflow:commit", json={
                    "workflow": saved["draft"]["workflow"],
                })
            elif operation == "version":
                response = http.post(f"{prefix}/versions", json={"name": "During run"})
            else:
                response = http.post(f"{prefix}/inputs", json={
                    "filename": "new.txt", "content_base64": "bmV3",
                })
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == "project_has_active_runs"
            assert http.get(f"{prefix}/workspace").json() == saved
            assert http.get(f"{prefix}/inputs").json() == original_inputs
            assert app.state.project_manager.require_meta(project_id).name == metadata.name
        finally:
            release.set()
        assert client.wait_terminal(project_id, started["run_id"])["status"] == "succeeded"
        editable = http.put(f"{prefix}/workspace", json={"ui_state": {"zoom": 9}})
        assert editable.status_code == 200, editable.text


def test_project_history_lists_success_and_failed_runs_with_retained_results_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    catalog = build_frozen_catalog((PROTEIN_IO_PACKAGE,))
    app = create_application(frozen_catalog_override=catalog)
    with TestClient(app) as http:
        client = PublicRunClient(http)
        project = http.post("/api/v2/projects", json={"name": "Run history"}).json()
        project_id = project["id"]
        prefix = f"/api/v2/projects/{project_id}"
        inputs = []
        for name, content in (("good", b">one\nACDE\n"), ("bad", b">one\nACDE\n>two\nGGGG\n")):
            response = http.post(f"{prefix}/inputs", json={
                "filename": f"{name}.fasta",
                "content_base64": base64.b64encode(content).decode("ascii"),
            })
            assert response.status_code == 201, response.text
            inputs.append(response.json()["project_input_ref"])
        workflow = _workflow(project_id, inputs[0])
        commit = client.commit_workflow(project_id, workflow)
        first = client.start_run(project_id, commit["workflow_commit_id"], request_id="history-success")
        success = client.wait_terminal(project_id, first["run_id"])
        assert success["status"] == "succeeded"
        bad_node = _workflow(project_id, inputs[1])["nodes"][0]
        bad_node["node_id"] = "invalid-import"
        workflow["nodes"].append(bad_node)
        commit = client.commit_workflow(project_id, workflow)
        second = client.start_run(project_id, commit["workflow_commit_id"], request_id="history-failure")
        failed = client.wait_terminal(project_id, second["run_id"])
        assert failed["status"] == "failed"
        assert failed["outputs"]
        expected = {run["run_id"]: {
            "run_id": run["run_id"],
            "workflow_commit_id": run["workflow_commit_id"],
            "status": run["status"],
            "has_results": True,
        } for run in (success, failed)}
        listed = http.get(f"{prefix}/runs")
        assert listed.status_code == 200, listed.text
        assert listed.json()["project_id"] == project_id
        assert {run["run_id"]: run for run in listed.json()["runs"]} == expected

    with TestClient(create_application(frozen_catalog_override=catalog)) as http:
        listed = http.get(f"{prefix}/runs")
        assert listed.status_code == 200, listed.text
        assert {run["run_id"]: run for run in listed.json()["runs"]} == expected
        for original in (success, failed):
            reopened = http.get(f"{prefix}/runs/{original['run_id']}")
            assert reopened.status_code == 200, reopened.text
            assert reopened.json() == original
