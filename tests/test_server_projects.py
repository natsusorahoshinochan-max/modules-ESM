"""Tests for project CRUD server endpoints."""

from fastapi.testclient import TestClient
import pytest

from core.project import CANONICAL_3GB1_PROJECT_ID, CanonicalSeedError
from core.server import app, create_app


class TestProjectEndpoints:
    def test_startup_lists_one_read_only_canonical_project(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "PROTEIN_WORKBENCH_PROJECT_ROOT",
            str(tmp_path / "projects"),
        )
        canonical_app = create_app()

        for _ in range(2):
            with TestClient(canonical_app) as client:
                projects = client.get("/api/projects").json()
                canonical = [
                    project
                    for project in projects
                    if project["id"] == CANONICAL_3GB1_PROJECT_ID
                ]
                assert len(canonical) == 1
                assert canonical[0]["seed"] is True
                assert canonical[0]["legacy_seed"] is False

                workflow = client.get(
                    f"/api/projects/{CANONICAL_3GB1_PROJECT_ID}/workflow"
                ).json()
                response = client.put(
                    f"/api/projects/{CANONICAL_3GB1_PROJECT_ID}/workflow",
                    json=workflow,
                )
                assert response.status_code == 403
                assert response.json()["error"]["kind"] == (
                    "protected_canonical_project"
                )
                ui_response = client.put(
                    f"/api/projects/{CANONICAL_3GB1_PROJECT_ID}/ui",
                    json={},
                )
                assert ui_response.status_code == 403
                upload_response = client.post(
                    f"/api/projects/{CANONICAL_3GB1_PROJECT_ID}/inputs",
                    files={"file": ("replacement.pdb", b"END\n")},
                )
                assert upload_response.status_code == 403

    def test_startup_surfaces_canonical_workflow_drift(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        invalid_workflow = tmp_path / "invalid.json"
        invalid_workflow.write_text(
            """
            {
              "nodes": [
                {
                  "node_id": "echo",
                  "module_id": "stub.echo",
                  "module_version": "outdated",
                  "parameters": {}
                }
              ],
              "edges": []
            }
            """
        )
        monkeypatch.setenv(
            "PROTEIN_WORKBENCH_PROJECT_ROOT",
            str(tmp_path / "projects"),
        )
        monkeypatch.setenv(
            "PROTEIN_WORKBENCH_CANONICAL_WORKFLOW",
            str(invalid_workflow),
        )

        with pytest.raises(
            CanonicalSeedError,
            match="module_version_mismatch",
        ):
            with TestClient(create_app()):
                pass

    def test_create_and_list_projects(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/projects", json={"name": "Server Test"})
            assert resp.status_code == 200
            meta = resp.json()
            assert meta["name"] == "Server Test"
            pid = meta["id"]

            resp = client.get("/api/projects")
            projects = resp.json()
            assert any(p["id"] == pid for p in projects)

    def test_get_project_meta(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/projects", json={"name": "Meta Test"})
            pid = resp.json()["id"]

            resp = client.get(f"/api/projects/{pid}")
            assert resp.status_code == 200
            assert resp.json()["name"] == "Meta Test"

    def test_get_nonexistent_project(self) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/projects/nonexistent")
            assert resp.status_code == 200
            assert "error" in resp.json()

    def test_save_and_load_workflow(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/projects", json={"name": "WF Test"})
            pid = resp.json()["id"]

            wf = {
                "nodes": [
                    {"node_id": "a", "module_id": "stub.echo", "parameters": {"repeat": 2}},
                    {"node_id": "b", "module_id": "stub.echo", "parameters": {"prefix": ">"}},
                ],
                "edges": [
                    {"source_node_id": "a", "source_port": "text",
                     "target_node_id": "b", "target_port": "text"},
                ],
            }
            resp = client.put(f"/api/projects/{pid}/workflow", json=wf)
            assert resp.status_code == 200

            resp = client.get(f"/api/projects/{pid}/workflow")
            loaded = resp.json()
            assert len(loaded["nodes"]) == 2
            assert len(loaded["edges"]) == 1

    def test_save_and_load_ui(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/projects", json={"name": "UI Test"})
            pid = resp.json()["id"]

            ui = {"node_positions": {"a": {"x": 10, "y": 20}}, "canvas_zoom": 2.0}
            resp = client.put(f"/api/projects/{pid}/ui", json=ui)
            assert resp.status_code == 200

            resp = client.get(f"/api/projects/{pid}/ui")
            loaded = resp.json()
            assert loaded["node_positions"]["a"]["x"] == 10
            assert loaded["canvas_zoom"] == 2.0

    def test_empty_workflow_loads(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/projects", json={"name": "Empty"})
            pid = resp.json()["id"]

            resp = client.get(f"/api/projects/{pid}/workflow")
            loaded = resp.json()
            assert loaded["nodes"] == []
            assert loaded["edges"] == []

    def test_empty_ui_loads(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/projects", json={"name": "EmptyUI"})
            pid = resp.json()["id"]

            resp = client.get(f"/api/projects/{pid}/ui")
            loaded = resp.json()
            assert loaded["node_positions"] == {}

    def test_missing_module_in_loaded_workflow(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/projects", json={"name": "MissingMod"})
            pid = resp.json()["id"]

            wf = {
                "nodes": [
                    {"node_id": "good", "module_id": "stub.echo"},
                    {"node_id": "bad", "module_id": "ghost.module"},
                ],
                "edges": [],
            }
            client.put(f"/api/projects/{pid}/workflow", json=wf)

            resp = client.get(f"/api/projects/{pid}/workflow")
            loaded = resp.json()
            good = next(n for n in loaded["nodes"] if n["node_id"] == "good")
            bad = next(n for n in loaded["nodes"] if n["node_id"] == "bad")
            assert good["available"] is True
            assert bad["available"] is False
