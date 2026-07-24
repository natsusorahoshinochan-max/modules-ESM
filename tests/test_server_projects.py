"""Tests for project CRUD server endpoints."""

from fastapi.testclient import TestClient
from core.server import app


class TestProjectEndpoints:
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
