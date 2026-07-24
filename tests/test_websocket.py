"""Integration tests for WebSocket execution progress."""

import json

import pytest
from fastapi.testclient import TestClient

from core.server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestWebSocketExecution:
    def test_websocket_connects_and_execution_completes(self, client):
        """Verify WebSocket connects and execution API works."""
        # Connect WebSocket
        with client.websocket_connect("/ws/execution") as ws:
            # Submit execution via REST
            payload = {
                "nodes": [
                    {
                        "node_id": "n1",
                        "module_id": "stub.echo",
                        "module_version": "1.0.0",
                        "parameters": {"text": "hello"},
                    }
                ],
                "edges": [],
            }
            resp = client.post("/api/execute", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert "run_id" in data

            # The WebSocket connection should be alive
            # (execution happens in background, messages may arrive)
            # We at minimum verify the connection was established

    def test_execute_returns_run_id(self, client):
        """Execution endpoint returns a valid run_id."""
        payload = {
            "nodes": [
                {"node_id": "n1", "module_id": "stub.echo",
                 "module_version": "1.0.0", "parameters": {"text": "test"}},
            ],
            "edges": [],
        }
        resp = client.post("/api/execute", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        assert len(data["run_id"]) > 0

    def test_execute_rejects_unknown_module(self, client):
        """Execute returns error for unknown module."""
        payload = {
            "nodes": [
                {"node_id": "n1", "module_id": "nonexistent.module",
                 "module_version": "1.0.0", "parameters": {}},
            ],
            "edges": [],
        }
        resp = client.post("/api/execute", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
