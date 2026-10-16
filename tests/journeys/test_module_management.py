"""User module lifecycle through the production public protocol."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


def test_disable_all_modules_preserves_saved_project_and_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    with TestClient(create_application(v2_environment_configuration={})) as http:
        listed = http.get("/api/v2/modules")
        assert listed.status_code == 200, listed.text
        assert listed.json()["modules"]
        assert all(module["enabled"] for module in listed.json()["modules"])
        created = http.post("/api/v2/projects", json={"name": "Retained after disabling"})
        project_id = created.json()["id"]
        workflow = {"schema_version": "2.1.0", "workflow_id": project_id, "nodes": [{
            "node_id": "input", "node_type_id": "protein_io.import_sequence",
            "binding_id": "protein_io.import_sequence.direct",
            "node_parameters": {}, "binding_parameters": {},
        }], "edges": []}
        saved = http.put(f"/api/v2/projects/{project_id}/workspace", json={"workflow": workflow})
        assert saved.status_code == 200, saved.text
        disabled = http.put("/api/v2/modules", json={"enabled_package_ids": []})
        assert disabled.status_code == 200, disabled.text
        assert not any(module["enabled"] for module in disabled.json()["modules"])
        assert not any(contract["reference"]["contract_kind"] in {"node_type", "binding"}
                       for contract in http.get("/api/v2/catalog").json()["contracts"])
        assert http.get(f"/api/v2/projects/{project_id}/workspace").json() == saved.json()
    with TestClient(create_application(v2_environment_configuration={})) as http:
        assert not any(module["enabled"] for module in http.get("/api/v2/modules").json()["modules"])
        assert http.get(f"/api/v2/projects/{project_id}/workspace").json() == saved.json()


def test_external_wheel_installs_runs_and_recovers_without_source_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64
    import json

    from tests.fixtures.external_module import build_external_module_wheel
    from tests.support.public_runs import PublicRunClient

    data_root = tmp_path / "application"
    data_root.mkdir()
    (data_root / "modules.json").write_text('{"packages": []}')
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(data_root))
    wheel = build_external_module_wheel(tmp_path / "external-distribution")
    upload = {"filename": wheel.name, "content_base64": base64.b64encode(wheel.read_bytes()).decode()}
    with TestClient(create_application(v2_environment_configuration={})) as http:
        installed = http.post("/api/v2/modules/install", json=upload)
        assert installed.status_code == 201, installed.text
        assert installed.json()["modules"] == [{
            "package_id": "external_echo", "package_module": "external_echo.package",
            "enabled": True, "origin": "external",
        }]
        project_id = http.post("/api/v2/projects", json={"name": "External module"}).json()["id"]
        workflow = {"schema_version": "2.1.0", "workflow_id": project_id, "nodes": [{
            "node_id": "echo", "node_type_id": "external.echo", "binding_id": "external.echo.direct",
            "node_parameters": {}, "binding_parameters": {},
        }], "edges": []}
        client = PublicRunClient(http)
        commit = client.commit_workflow(project_id, workflow)
        receipt = client.start_run(project_id, commit["workflow_commit_id"], request_id="external-first")
        run = client.wait_terminal(project_id, receipt["run_id"])
        assert run["status"] == "succeeded", run
        assert json.loads(client.typed_output_bytes(project_id, receipt["run_id"], run["outputs"][0], 0))["value"] == "installed external value"
        saved = http.get(f"/api/v2/projects/{project_id}/workspace").json()
        removed = http.delete("/api/v2/modules/external_echo")
        assert removed.status_code == 200, removed.text
        assert removed.json()["modules"] == []
        assert http.get(f"/api/v2/projects/{project_id}/workspace").json() == saved
        assert http.post(f"/api/v2/projects/{project_id}/workflow:commit", json={"workflow": workflow}).status_code == 422
        restored = http.post("/api/v2/modules/install", json=upload)
        assert restored.status_code == 201, restored.text
        commit = client.commit_workflow(project_id, workflow)
        receipt = client.start_run(project_id, commit["workflow_commit_id"], request_id="external-restored")
        assert client.wait_terminal(project_id, receipt["run_id"])["status"] == "succeeded"
    with TestClient(create_application(v2_environment_configuration={})) as http:
        assert http.get("/api/v2/modules").json()["modules"][0]["enabled"] is True
        assert http.get(f"/api/v2/projects/{project_id}/workspace").json()["draft"]["workflow"]["nodes"] == workflow["nodes"]


def test_missing_module_teaching_first_save_uses_recorded_input_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    with TestClient(create_application(v2_environment_configuration={})) as http:
        source = "/api/v2/projects/webui-3gb1-example"
        original = http.get(f"{source}/workspace").json()
        inputs = http.get(f"{source}/inputs").json()["inputs"]
        assert inputs
        assert http.put("/api/v2/modules", json={"enabled_package_ids": []}).status_code == 200
        copied = http.post(f"{source}:copy", json={"name": "Missing-module teaching copy",
            "workflow": original["draft"]["workflow"], "ui_state": original["ui_state"]})
        assert copied.status_code == 201, copied.text
        target = f"/api/v2/projects/{copied.json()['id']}"
        assert http.get(f"{target}/workspace").json()["draft"]["workflow"]["nodes"] == original["draft"]["workflow"]["nodes"]
        target_inputs = http.get(f"{target}/inputs").json()["inputs"]
        assert {(item["project_input_ref"], item["content_digest"]) for item in target_inputs} == {
            (item["project_input_ref"], item["content_digest"]) for item in inputs}
        assert http.get(f"{source}/workspace").json() == original
