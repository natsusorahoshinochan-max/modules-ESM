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
