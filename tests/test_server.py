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


def test_types_returns_json_content_type() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/types")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]


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
            for port in mod["output_ports"]:
                assert "name" in port
                assert "type_id" in port
            # Each parameter has required fields
            for param in mod["parameters"]:
                assert "name" in param
                assert "type" in param
                assert "default" in param
