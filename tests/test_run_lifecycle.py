"""Client-observable run lifecycle contracts."""

from __future__ import annotations

from datetime import datetime
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import core.server as server
from core.module_definition import ModuleDefinition, PortDefinition
from core.run_context import RunContext
from core.run_manifest import read_run_manifest
from core.workflow_module import WorkflowModule


class FailingLifecycleModule(WorkflowModule):
    @property
    def definition(self) -> ModuleDefinition:
        return ModuleDefinition(
            module_id="test.lifecycle_failure",
            version="1.0.0",
            display_name="Lifecycle failure",
            category="input",
            output_ports=[PortDefinition("text", "text")],
        )

    def run(
        self,
        inputs: dict[str, object],
        parameters: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        del inputs, parameters, context
        raise RuntimeError("authorization=Bearer lifecycle-secret")


class SlowLifecycleModule(WorkflowModule):
    @property
    def definition(self) -> ModuleDefinition:
        return ModuleDefinition(
            module_id="test.lifecycle_slow",
            version="1.0.0",
            display_name="Lifecycle slow",
            category="input",
            output_ports=[PortDefinition("text", "text")],
        )

    def run(
        self,
        inputs: dict[str, object],
        parameters: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        del inputs, parameters, context
        time.sleep(0.5)
        return {"text": "finished"}


def _saved_echo_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"name": name})
    project_id = response.json()["id"]
    workflow = {
        "nodes": [
            {
                "node_id": "echo",
                "module_id": "stub.echo",
                "module_version": "1.0.0",
                "parameters": {"text": "ordered"},
            }
        ],
        "edges": [],
    }
    saved = client.put(
        f"/api/projects/{project_id}/workflow",
        json=workflow,
    )
    assert saved.status_code == 200
    return project_id


def _receive_run_events(
    client: TestClient,
    project_id: str,
    run_id: str,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    with client.websocket_connect(
        f"/api/projects/{project_id}/run/{run_id}/ws"
    ) as websocket:
        while True:
            event = websocket.receive_json()
            events.append(event)
            if event["type"] in {
                "run_completed",
                "run_failed",
                "run_cancelled",
            }:
                return events


def test_saved_workflow_emits_ordered_run_scoped_success_events() -> None:
    with TestClient(server.app) as client:
        project_id = _saved_echo_project(client, "ordered-success")

        response = client.post(
            f"/api/projects/{project_id}/run",
            json={"seed": 73},
        )

        assert response.status_code == 200
        run_id = response.json()["run_id"]
        events = _receive_run_events(client, project_id, run_id)
        manifest = read_run_manifest(
            server.project_manager.run_dir(project_id, run_id)
        )

    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert [event["type"] for event in events] == [
        "run_started",
        "node_state",
        "node_state",
        "node_completed",
        "run_completed",
    ]
    assert [event.get("node_id") for event in events] == [
        None,
        "echo",
        "echo",
        "echo",
        None,
    ]
    for event in events:
        assert event["project_id"] == project_id
        assert event["run_id"] == run_id
        assert datetime.fromisoformat(str(event["timestamp"])).tzinfo is not None
    assert events[-1]["status"] == "completed"
    assert manifest["status"] == "completed"
    assert manifest["node_states"][-1]["state"] == "completed"


def test_failure_blocks_dependent_once_and_unrelated_branch_completes() -> None:
    with TestClient(server.app) as client:
        server.module_registry.register(FailingLifecycleModule().definition)
        server.register_module_factory(
            "test.lifecycle_failure",
            FailingLifecycleModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "failure-branches"},
        ).json()["id"]
        workflow = {
            "nodes": [
                {
                    "node_id": "fails",
                    "module_id": "test.lifecycle_failure",
                    "module_version": "1.0.0",
                },
                {
                    "node_id": "dependent",
                    "module_id": "stub.echo",
                    "module_version": "1.0.0",
                },
                {
                    "node_id": "unrelated",
                    "module_id": "stub.echo",
                    "module_version": "1.0.0",
                    "parameters": {"prefix": "still-runs"},
                },
            ],
            "edges": [
                {
                    "source_node_id": "fails",
                    "source_port": "text",
                    "target_node_id": "dependent",
                    "target_port": "text",
                }
            ],
        }
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json=workflow,
        ).status_code == 200

        response = client.post(
            f"/api/projects/{project_id}/run",
            json={},
        )
        run_id = response.json()["run_id"]
        events = _receive_run_events(client, project_id, run_id)
        manifest = read_run_manifest(
            server.project_manager.run_dir(project_id, run_id)
        )

    terminal_events = [
        event
        for event in events
        if event["type"]
        in {
            "node_completed",
            "node_failed",
            "node_blocked",
            "node_cancelled",
        }
    ]
    assert [
        (event["node_id"], event["type"])
        for event in terminal_events
    ] == [
        ("fails", "node_failed"),
        ("unrelated", "node_completed"),
        ("dependent", "node_blocked"),
    ]
    assert len([
        event
        for event in events
        if event["type"] == "node_blocked"
        and event["node_id"] == "dependent"
    ]) == 1
    failed = next(
        event for event in events if event["type"] == "node_failed"
    )
    assert failed["diagnostic"] == {
        "kind": "RuntimeError",
        "message": "Node execution failed (RuntimeError)",
        "module_id": "test.lifecycle_failure",
        "retryable": False,
    }
    assert "lifecycle-secret" not in str(events)
    assert events[-1]["type"] == "run_failed"
    assert events[-1]["status"] == "failed"
    assert manifest["status"] == "failed"
    assert manifest["blocking_reasons"] == [
        {
            "node_id": "dependent",
            "reason": {
                "kind": "upstream_terminal",
                "message": "Required upstream Node did not complete",
                "upstream_node_ids": ["fails"],
            },
        }
    ]


def test_run_subscriber_cannot_cross_project_or_run_scope() -> None:
    with TestClient(server.app) as client:
        project_a = _saved_echo_project(client, "scope-a")
        project_b = _saved_echo_project(client, "scope-b")
        run_a = client.post(
            f"/api/projects/{project_a}/run",
            json={},
        ).json()["run_id"]
        run_b = client.post(
            f"/api/projects/{project_b}/run",
            json={},
        ).json()["run_id"]

        events_a = _receive_run_events(client, project_a, run_a)
        events_b = _receive_run_events(client, project_b, run_b)
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                f"/api/projects/{project_a}/run/{run_b}/ws"
            ):
                pass

    assert rejected.value.code == 4404
    assert {
        (event["project_id"], event["run_id"])
        for event in events_a
    } == {(project_a, run_a)}
    assert {
        (event["project_id"], event["run_id"])
        for event in events_b
    } == {(project_b, run_b)}


def test_cache_hit_preserves_fresh_run_event_ordering() -> None:
    with TestClient(server.app) as client:
        project_id = _saved_echo_project(client, "cache-parity")
        run_ids = [
            client.post(
                f"/api/projects/{project_id}/run",
                json={},
            ).json()["run_id"]
            for _ in range(2)
        ]
        fresh_events = _receive_run_events(
            client,
            project_id,
            run_ids[0],
        )
        cached_events = _receive_run_events(
            client,
            project_id,
            run_ids[1],
        )
        manifests = [
            read_run_manifest(
                server.project_manager.run_dir(project_id, run_id)
            )
            for run_id in run_ids
        ]

    assert [event["type"] for event in cached_events] == [
        event["type"] for event in fresh_events
    ]
    assert [event["sequence"] for event in cached_events] == list(
        range(1, len(cached_events) + 1)
    )
    fresh_terminal = next(
        event
        for event in fresh_events
        if event["type"] == "node_completed"
    )
    cached_terminal = next(
        event
        for event in cached_events
        if event["type"] == "node_completed"
    )
    assert fresh_terminal["cache"] == {"outcome": "miss"}
    assert cached_terminal["cache"] == {"outcome": "hit"}
    assert [manifest["status"] for manifest in manifests] == [
        "completed",
        "completed",
    ]
    assert [manifest["cache"][0]["outcome"] for manifest in manifests] == [
        "miss",
        "hit",
    ]


def test_cancelled_run_remains_distinct_from_failed_or_completed() -> None:
    with TestClient(server.app) as client:
        server.module_registry.register(SlowLifecycleModule().definition)
        server.register_module_factory(
            "test.lifecycle_slow",
            SlowLifecycleModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "cancelled-distinction"},
        ).json()["id"]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={
                "nodes": [
                    {
                        "node_id": "slow",
                        "module_id": "test.lifecycle_slow",
                        "module_version": "1.0.0",
                    }
                ],
                "edges": [],
            },
        ).status_code == 200

        run_id = client.post(
            f"/api/projects/{project_id}/run"
        ).json()["run_id"]
        events = []
        with client.websocket_connect(
            f"/api/projects/{project_id}/run/{run_id}/ws"
        ) as websocket:
            events.append(websocket.receive_json())
            cancelled = client.post(
                "/api/execute/cancel",
                json={"run_id": run_id},
            )
            while events[-1]["type"] != "run_cancelled":
                events.append(websocket.receive_json())
        manifest = read_run_manifest(
            server.project_manager.run_dir(project_id, run_id)
        )

    assert cancelled.json()["status"] == "cancelled"
    assert events[-1]["type"] == "run_cancelled"
    assert events[-1]["status"] == "cancelled"
    assert not any(
        event["type"] in {"run_completed", "run_failed"}
        for event in events
    )
    assert manifest["status"] == "cancelled"
    assert manifest["node_states"][-1]["state"] == "cancelled"
