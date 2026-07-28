"""Tests for FastAPI server endpoints."""

from fastapi.testclient import TestClient
from core.server import app


def test_list_modules_returns_stub_module() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/modules")
        assert resp.status_code == 200
        modules = resp.json()
        assert len(modules) >= 1
        # Find the stub echo module
        echo = next((m for m in modules if m["module_id"] == "stub.echo"), None)
        assert echo is not None
        assert echo["category"] == "input"
        assert echo["version"] == "1.0.0"
        # Verify shape
        assert "input_ports" in echo
        assert "output_ports" in echo
        assert "parameters" in echo
        assert len(echo["input_ports"]) > 0
        assert len(echo["output_ports"]) > 0


def test_list_types_returns_text_type() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/types")
        assert resp.status_code == 200
        types = resp.json()
        assert "text" in types


def test_modules_returns_json_content_type() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/modules")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]


def test_module_api_exposes_standalone_artifact_port_opt_in() -> None:
    with TestClient(app) as client:
        modules = client.get("/api/modules").json()

    export_sequence = next(
        module
        for module in modules
        if module["module_id"] == "export.sequence"
    )
    file_path = next(
        port
        for port in export_sequence["output_ports"]
        if port["name"] == "file_path"
    )
    assert file_path["artifact_kind"] == "standalone"


def test_types_returns_json_content_type() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/types")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]


def test_cors_rejects_foreign_origins_and_allows_local_frontend() -> None:
    with TestClient(app) as client:
        foreign_execution = client.post(
            "/api/execute",
            headers={"Origin": "https://attacker.example"},
            json={
                "nodes": [
                    {
                        "node_id": "echo",
                        "module_id": "stub.echo",
                        "module_version": "1.0.0",
                    }
                ],
                "edges": [],
            },
        )
        foreign = client.options(
            "/api/execute",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        local = client.options(
            "/api/execute",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert foreign_execution.status_code == 403
    assert foreign_execution.json()["error"]["kind"] == "untrusted_origin"
    assert "access-control-allow-origin" not in foreign.headers
    assert local.headers["access-control-allow-origin"] == (
        "http://127.0.0.1:5173"
    )


def test_module_definition_shape() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/modules")
        modules = resp.json()
        for mod in modules:
            assert "module_id" in mod
            assert "version" in mod
            assert "display_name" in mod
            assert "category" in mod
            assert "description" in mod
            assert "input_ports" in mod
            assert "output_ports" in mod
            assert "parameters" in mod
            assert "module_api" in mod
            # Each port has required fields
            for port in mod["input_ports"]:
                assert "name" in port
                assert "type_id" in port
                assert "required" in port
                assert "allow_multiple" in port
            for port in mod["output_ports"]:
                assert "name" in port
                assert "type_id" in port
            # Each parameter has required fields
            for param in mod["parameters"]:
                assert "name" in param
                assert "type" in param
                assert "default" in param


def test_execute_rejects_invalid_workflow_before_creating_run(
    monkeypatch,
) -> None:
    payload = {
        "nodes": [
            {
                "node_id": "source",
                "module_id": "import.sequence",
                "module_version": "1.0.0",
            },
            {
                    "node_id": "target",
                    "module_id": "esm3.generate",
                    "module_version": "1.2.0",
            },
        ],
        "edges": [
            {
                "source_node_id": "source",
                "source_port": "sequence",
                "target_node_id": "target",
                "target_port": "protein_prompt",
            }
        ],
    }

    from modules import esm3_adapter

    provider_calls = []

    def unexpected_provider_call(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("invalid Workflow invoked a provider")

    monkeypatch.setattr(
        esm3_adapter,
        "create_esm3_client",
        unexpected_provider_call,
    )

    with TestClient(app) as client:
        response = client.post("/api/execute", json=payload)

        assert response.status_code == 422
        assert response.json() == {
            "valid": False,
            "errors": [
                {
                    "kind": "port_type_mismatch",
                    "message": (
                        "Source Port type 'protein.sequence' does not exactly "
                        "match target Port type 'protein.prompt'"
                    ),
                    "node_id": "target",
                    "module_id": "esm3.generate",
                    "port": "protein_prompt",
                }
            ],
        }
        assert "run_id" not in response.json()
        assert provider_calls == []


def test_execute_returns_structured_error_for_duplicate_node_id() -> None:
    payload = {
        "nodes": [
            {
                "node_id": "duplicate",
                "module_id": "stub.echo",
                "module_version": "1.0.0",
            },
            {
                "node_id": "duplicate",
                "module_id": "stub.echo",
                "module_version": "1.0.0",
            },
        ],
        "edges": [],
    }

    with TestClient(app) as client:
        response = client.post("/api/execute", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "valid": False,
        "errors": [
            {
                "kind": "duplicate_node_id",
                "message": "Node ID 'duplicate' appears more than once",
                "node_id": "duplicate",
                "module_id": "stub.echo",
            }
        ],
    }


def test_execute_returns_structured_error_for_dangling_edge() -> None:
    payload = {
        "nodes": [
            {
                "node_id": "target",
                "module_id": "stub.echo",
                "module_version": "1.0.0",
            }
        ],
        "edges": [
            {
                "source_node_id": "missing",
                "source_port": "text",
                "target_node_id": "target",
                "target_port": "text",
            }
        ],
    }

    with TestClient(app) as client:
        response = client.post("/api/execute", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "valid": False,
        "errors": [
            {
                "kind": "edge_node_not_found",
                "message": "Source Node 'missing' is not in the Workflow",
                "node_id": "missing",
                "port": "text",
            }
        ],
    }


def test_execute_returns_structured_error_for_invalid_node_field_type() -> None:
    payload = {
        "nodes": [
            {
                "node_id": [],
                "module_id": "stub.echo",
                "module_version": "1.0.0",
            }
        ],
        "edges": [],
    }

    with TestClient(app) as client:
        response = client.post("/api/execute", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "valid": False,
        "errors": [
            {
                "kind": "malformed_workflow",
                "message": "Workflow Node fields must be strings: node_id",
            }
        ],
    }


def test_execute_returns_structured_error_for_invalid_edge_field_type() -> None:
    payload = {
        "nodes": [
            {
                "node_id": "source",
                "module_id": "stub.echo",
                "module_version": "1.0.0",
            },
            {
                "node_id": "target",
                "module_id": "stub.echo",
                "module_version": "1.0.0",
            },
        ],
        "edges": [
            {
                "source_node_id": "source",
                "source_port": ["text"],
                "target_node_id": "target",
                "target_port": "text",
            }
        ],
    }

    with TestClient(app) as client:
        response = client.post("/api/execute", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "valid": False,
        "errors": [
            {
                "kind": "malformed_workflow",
                "message": (
                    "Workflow Edge fields must be strings: source_port"
                ),
            }
        ],
    }
