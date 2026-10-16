"""Empty installations retain Project operations through production startup."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from protein_workbench_public.bootstrap import create_application


def test_empty_carrier_saves_and_reopens_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    (tmp_path / "modules.json").write_text(json.dumps({"packages": []}))
    with TestClient(create_application()) as client:
        assert client.get("/api/v2/catalog").json()["contracts"] == []
        assert client.get("/api/v2/projects").json()["projects"] == []
        created = client.post("/api/v2/projects", json={"name": "Empty carrier"})
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        workflow = {"schema_version": "2.1.0", "workflow_id": project_id,
                    "nodes": [], "edges": []}
        saved = client.put(f"/api/v2/projects/{project_id}/workspace", json={
            "workflow": workflow, "ui_state": {"canvas": {"zoom": 1.2}},
        })
        assert saved.status_code == 200, saved.text
        snapshot = saved.json()
    with TestClient(create_application()) as client:
        assert client.get(f"/api/v2/projects/{project_id}/workspace").json() == snapshot
        assert client.get("/api/v2/projects").json()["projects"][0]["name"] == "Empty carrier"
