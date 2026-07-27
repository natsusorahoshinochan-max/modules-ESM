"""Client-observable run lifecycle contracts."""

from __future__ import annotations

import asyncio
from datetime import datetime
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import core.server as server
import core.executor as executor_module
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


class BlockingLifecycleModule(WorkflowModule):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    @property
    def definition(self) -> ModuleDefinition:
        return ModuleDefinition(
            module_id="test.lifecycle_blocking",
            version="1.0.0",
            display_name="Lifecycle blocking",
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
        self.started.set()
        try:
            self.release.wait(timeout=5)
            return {"text": "finished"}
        finally:
            self.finished.set()


class CancellableAsyncLifecycleModule(WorkflowModule):
    started = threading.Event()
    stopped = threading.Event()

    @property
    def definition(self) -> ModuleDefinition:
        return ModuleDefinition(
            module_id="test.lifecycle_cancellable_async",
            version="1.0.0",
            display_name="Lifecycle cancellable async",
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
        raise AssertionError("The async cancellation boundary must be used")

    async def run_async(
        self,
        inputs: dict[str, object],
        parameters: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        del inputs, parameters, context
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.stopped.set()


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


def _saved_blocking_project(client: TestClient, name: str) -> str:
    BlockingLifecycleModule.started.clear()
    BlockingLifecycleModule.release.clear()
    BlockingLifecycleModule.finished.clear()
    server.module_registry.register(BlockingLifecycleModule().definition)
    server.register_module_factory(
        "test.lifecycle_blocking",
        BlockingLifecycleModule,
    )
    project_id = client.post(
        "/api/projects",
        json={"name": name},
    ).json()["id"]
    assert client.put(
        f"/api/projects/{project_id}/workflow",
        json={
            "nodes": [
                {
                    "node_id": "blocking",
                    "module_id": "test.lifecycle_blocking",
                    "module_version": "1.0.0",
                }
            ],
            "edges": [],
        },
    ).status_code == 200
    return project_id


def _saved_cancellable_async_project(
    client: TestClient,
    name: str,
) -> str:
    CancellableAsyncLifecycleModule.started.clear()
    CancellableAsyncLifecycleModule.stopped.clear()
    module = CancellableAsyncLifecycleModule()
    server.module_registry.register(module.definition)
    server.register_module_factory(
        "test.lifecycle_cancellable_async",
        CancellableAsyncLifecycleModule,
    )
    project_id = client.post(
        "/api/projects",
        json={"name": name},
    ).json()["id"]
    assert client.put(
        f"/api/projects/{project_id}/workflow",
        json={
            "nodes": [
                {
                    "node_id": "provider",
                    "module_id": "test.lifecycle_cancellable_async",
                    "module_version": "1.0.0",
                }
            ],
            "edges": [],
        },
    ).status_code == 200
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
    timestamps = [
        datetime.fromisoformat(str(event["timestamp"]))
        for event in events
    ]
    assert timestamps == sorted(timestamps)
    assert events[-1]["status"] == "completed"
    assert isinstance(events[-1]["duration_ms"], int)
    assert manifest["status"] == "completed"
    assert manifest["node_states"][-1]["state"] == "completed"


def test_project_rejects_second_run_while_first_run_is_active() -> None:
    with TestClient(server.app) as client:
        project_id = _saved_blocking_project(
            client,
            "same-project-exclusion",
        )
        first = client.post(f"/api/projects/{project_id}/run")
        assert first.status_code == 200
        first_run_id = first.json()["run_id"]
        assert BlockingLifecycleModule.started.wait(timeout=2)

        overlapping = client.post(f"/api/projects/{project_id}/run")
        BlockingLifecycleModule.release.set()
        _receive_run_events(client, project_id, first_run_id)

    assert overlapping.status_code == 409
    assert overlapping.json() == {
        "error": {
            "kind": "active_run_conflict",
            "message": "Project already has an active run",
            "project_id": project_id,
            "active_run_id": first_run_id,
        }
    }


def test_node_terminal_manifest_fact_exists_before_run_terminal_event() -> None:
    with TestClient(server.app) as client:
        server.module_registry.register(SlowLifecycleModule().definition)
        server.register_module_factory(
            "test.lifecycle_slow",
            SlowLifecycleModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "manifest-before-terminal"},
        ).json()["id"]
        assert client.put(
            f"/api/projects/{project_id}/workflow",
            json={
                "nodes": [
                    {
                        "node_id": "first",
                        "module_id": "stub.echo",
                        "module_version": "1.0.0",
                    },
                    {
                        "node_id": "wait",
                        "module_id": "test.lifecycle_slow",
                        "module_version": "1.0.0",
                    },
                ],
                "edges": [],
            },
        ).status_code == 200
        run_id = client.post(
            f"/api/projects/{project_id}/run"
        ).json()["run_id"]

        observed_types: list[str] = []
        with client.websocket_connect(
            f"/api/projects/{project_id}/run/{run_id}/ws"
        ) as websocket:
            while True:
                event = websocket.receive_json()
                observed_types.append(event["type"])
                if (
                    event["type"] == "node_completed"
                    and event["node_id"] == "first"
                ):
                    in_progress_manifest = read_run_manifest(
                        server.project_manager.run_dir(project_id, run_id)
                    )
                    assert in_progress_manifest["status"] == "running"
                    persisted_terminal = next(
                        state
                        for state in in_progress_manifest["node_states"]
                        if (
                            state["node_id"] == "first"
                            and state["state"] == "completed"
                        )
                    )
                    assert {
                        key: persisted_terminal[key]
                        for key in (
                            "sequence",
                            "node_id",
                            "old_state",
                            "state",
                        )
                    } == {
                        "sequence": 4,
                        "node_id": "first",
                        "old_state": "running",
                        "state": "completed",
                    }
                    assert datetime.fromisoformat(
                        persisted_terminal["timestamp"]
                    ) <= datetime.fromisoformat(event["timestamp"])
                    assert not any(
                        event_type.startswith("run_")
                        and event_type != "run_started"
                        for event_type in observed_types
                    )
                if event["type"] == "run_completed":
                    break

    assert "node_completed" in observed_types
    assert observed_types[-1] == "run_completed"


def test_accepted_run_gets_safe_terminal_event_when_manifest_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_manifest_setup(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("authorization=Bearer setup-secret")

    with TestClient(server.app) as client:
        project_id = _saved_echo_project(client, "setup-failure")
        monkeypatch.setattr(
            executor_module,
            "RunManifestStore",
            fail_manifest_setup,
        )

        response = client.post(
            f"/api/projects/{project_id}/run"
        )

        assert response.status_code == 200
        run_id = response.json()["run_id"]
        events = _receive_run_events(client, project_id, run_id)

    assert [event["type"] for event in events] == ["run_failed"]
    assert events[0]["status"] == "failed"
    assert events[0]["error"] == {
        "kind": "run_setup_error",
        "message": "Run setup failed",
        "retryable": False,
    }
    assert "setup-secret" not in str(events)


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
    assert failed["error"] == {
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


def test_scoped_run_routes_reject_identifier_injection() -> None:
    with TestClient(server.app) as client:
        project_id = _saved_echo_project(client, "identifier-injection")

        response = client.post(
            f"/api/projects/{project_id}/run",
            json={"force_rerun_nodes": ["../../outside"]},
        )
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                f"/api/projects/{project_id}/run/not!valid/ws"
            ):
                pass

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "kind": "invalid_storage_path",
            "field": "node_id",
            "message": "Invalid node_id",
        }
    }
    assert rejected.value.code == 4400


def test_oversized_run_is_rejected_before_stream_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "MAX_RUN_NODES", 1)
    with TestClient(server.app) as client:
        response = client.post(
            "/api/execute",
            json={
                "nodes": [
                    {
                        "node_id": "first",
                        "module_id": "stub.echo",
                        "module_version": "1.0.0",
                    },
                    {
                        "node_id": "second",
                        "module_id": "stub.echo",
                        "module_version": "1.0.0",
                    },
                ],
                "edges": [],
            },
        )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "kind": "run_capacity_exceeded",
        "message": "Workflow exceeds run lifecycle capacity",
        "nodes": 2,
        "edges": 0,
        "limits": {"nodes": 1, "edges": 8192},
    }
    assert "run_id" not in response.json()


def test_cache_hit_preserves_fresh_run_event_ordering() -> None:
    with TestClient(server.app) as client:
        project_id = _saved_echo_project(client, "cache-parity")
        first_run_id = client.post(
            f"/api/projects/{project_id}/run",
            json={},
        ).json()["run_id"]
        fresh_events = _receive_run_events(
            client,
            project_id,
            first_run_id,
        )
        second_run_id = client.post(
            f"/api/projects/{project_id}/run",
            json={},
        ).json()["run_id"]
        cached_events = _receive_run_events(
            client,
            project_id,
            second_run_id,
        )
        run_ids = [first_run_id, second_run_id]
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
    assert fresh_terminal["output_summary"] == {
        "output_ports": ["text"],
        "cache": {"outcome": "miss"},
    }
    assert cached_terminal["output_summary"] == {
        "output_ports": ["text"],
        "cache": {"outcome": "hit"},
    }
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
        project_id = _saved_blocking_project(
            client,
            "cancelled-distinction",
        )
        run_id = client.post(f"/api/projects/{project_id}/run").json()["run_id"]
        assert BlockingLifecycleModule.started.wait(timeout=2)
        events = []
        with client.websocket_connect(
            f"/api/projects/{project_id}/run/{run_id}/ws"
        ) as websocket:
            while not (
                events
                and events[-1]["type"] == "node_state"
                and events[-1]["state"] == "running"
            ):
                events.append(websocket.receive_json())
            cancelled = client.post(
                f"/api/projects/{project_id}/run/{run_id}/cancel",
            )
            cancellation_requested = websocket.receive_json()
            manifest_while_blocked = read_run_manifest(
                server.project_manager.run_dir(project_id, run_id)
            )
            overlapping = client.post(f"/api/projects/{project_id}/run")
            BlockingLifecycleModule.release.set()
            while events[-1]["type"] != "run_cancelled":
                events.append(websocket.receive_json())
        manifest = read_run_manifest(
            server.project_manager.run_dir(project_id, run_id)
        )
        later = client.post(f"/api/projects/{project_id}/run")
        later_run_id = later.json()["run_id"]
        later_events = _receive_run_events(
            client,
            project_id,
            later_run_id,
        )

    assert cancelled.json() == {
        "status": "cancellation_requested",
        "project_id": project_id,
        "run_id": run_id,
    }
    assert cancellation_requested["type"] == "run_cancellation_requested"
    assert cancellation_requested["status"] == "cancellation_requested"
    assert manifest_while_blocked["status"] == "cancellation_requested"
    assert overlapping.status_code == 409
    assert events[-1]["type"] == "run_cancelled"
    assert events[-1]["status"] == "cancelled"
    assert not any(
        event["type"] in {"run_completed", "run_failed"}
        for event in events
    )
    assert manifest["status"] == "cancelled"
    assert manifest["node_states"][-1]["state"] == "cancelled"
    assert later.status_code == 200
    assert later_events[-1]["type"] == "run_completed"


def test_controllable_async_work_stops_before_cancelled_terminal() -> None:
    with TestClient(server.app) as client:
        project_id = _saved_cancellable_async_project(
            client,
            "controllable-cancellation",
        )
        run_id = client.post(f"/api/projects/{project_id}/run").json()["run_id"]
        assert CancellableAsyncLifecycleModule.started.wait(timeout=2)
        with client.websocket_connect(
            f"/api/projects/{project_id}/run/{run_id}/ws"
        ) as websocket:
            response = client.post(
                f"/api/projects/{project_id}/run/{run_id}/cancel",
            )
            events = []
            while not (
                events
                and events[-1]["type"] == "run_cancelled"
            ):
                events.append(websocket.receive_json())
        manifest = read_run_manifest(
            server.project_manager.run_dir(project_id, run_id)
        )

    assert response.json()["status"] == "cancellation_requested"
    assert CancellableAsyncLifecycleModule.stopped.is_set()
    assert [event["type"] for event in events][-3:] == [
        "run_cancellation_requested",
        "node_cancelled",
        "run_cancelled",
    ]
    assert manifest["status"] == "cancelled"


def test_cancellation_is_project_scoped_and_rejects_run_id_injection() -> None:
    with TestClient(server.app) as client:
        project_a = _saved_blocking_project(client, "cancel-scope-a")
        project_b = _saved_echo_project(client, "cancel-scope-b")
        run_a = client.post(f"/api/projects/{project_a}/run").json()["run_id"]
        assert BlockingLifecycleModule.started.wait(timeout=2)

        cross_project = client.post(
            f"/api/projects/{project_b}/run/{run_a}/cancel",
        )
        unscoped = client.post(
            "/api/execute/cancel",
            json={"run_id": run_a},
        )
        injected = client.post(
            f"/api/projects/{project_a}/run/not!valid/cancel",
        )
        manifest_before_owner_request = read_run_manifest(
            server.project_manager.run_dir(project_a, run_a)
        )
        owner = client.post(
            f"/api/projects/{project_a}/run/{run_a}/cancel",
        )
        BlockingLifecycleModule.release.set()
        events = _receive_run_events(client, project_a, run_a)

    assert cross_project.status_code == 404
    assert cross_project.json()["error"]["kind"] == "active_run_not_found"
    assert unscoped.json() == {
        "status": "project_scope_required",
        "run_id": run_a,
    }
    assert injected.status_code == 422
    assert injected.json()["error"] == {
        "kind": "invalid_storage_path",
        "field": "run_id",
        "message": "Invalid run_id",
    }
    assert manifest_before_owner_request["status"] == "running"
    assert owner.json()["status"] == "cancellation_requested"
    assert events[-1]["type"] == "run_cancelled"


def test_cancellation_persistence_error_falls_back_to_failed_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_set_status = executor_module.RunManifestStore.set_status
    cancellation_write_failed = False

    def fail_first_cancel_status(
        store: executor_module.RunManifestStore,
        status: str,
    ) -> None:
        nonlocal cancellation_write_failed
        if status == "cancelled" and not cancellation_write_failed:
            cancellation_write_failed = True
            raise OSError("transient terminal write failure")
        original_set_status(store, status)

    monkeypatch.setattr(
        executor_module.RunManifestStore,
        "set_status",
        fail_first_cancel_status,
    )
    with TestClient(server.app) as client:
        server.module_registry.register(SlowLifecycleModule().definition)
        server.register_module_factory(
            "test.lifecycle_slow",
            SlowLifecycleModule,
        )
        project_id = client.post(
            "/api/projects",
            json={"name": "cancel-persistence-failure"},
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
            assert client.post(
                f"/api/projects/{project_id}/run/{run_id}/cancel",
            ).json()["status"] == "cancellation_requested"
            while events[-1]["type"] != "run_failed":
                events.append(websocket.receive_json())
        manifest = read_run_manifest(
            server.project_manager.run_dir(project_id, run_id)
        )

    assert cancellation_write_failed is True
    assert events[-1]["error"]["kind"] == "terminal_persistence_error"
    assert manifest["status"] == "failed"


def test_cancellation_timeout_fails_and_isolates_the_later_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "RUN_CANCELLATION_TIMEOUT_SECONDS",
        0.05,
    )
    with TestClient(server.app) as client:
        project_id = _saved_blocking_project(
            client,
            "cancellation-timeout",
        )
        run_id = client.post(f"/api/projects/{project_id}/run").json()["run_id"]
        assert BlockingLifecycleModule.started.wait(timeout=2)
        with client.websocket_connect(
            f"/api/projects/{project_id}/run/{run_id}/ws"
        ) as websocket:
            assert client.post(
                f"/api/projects/{project_id}/run/{run_id}/cancel",
            ).json()["status"] == "cancellation_requested"
            events = []
            while not (
                events
                and events[-1]["type"] == "run_failed"
            ):
                events.append(websocket.receive_json())
        timed_out_manifest = read_run_manifest(
            server.project_manager.run_dir(project_id, run_id)
        )
        still_excluded = client.post(f"/api/projects/{project_id}/run")

        BlockingLifecycleModule.release.set()
        assert BlockingLifecycleModule.finished.wait(timeout=2)
        deadline = time.monotonic() + 2
        while True:
            later = client.post(f"/api/projects/{project_id}/run")
            if later.status_code != 409 or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        later_run_id = later.json()["run_id"]
        later_events = _receive_run_events(
            client,
            project_id,
            later_run_id,
        )
        later_manifest = read_run_manifest(
            server.project_manager.run_dir(project_id, later_run_id)
        )

    assert events[-1]["status"] == "failed"
    assert events[-1]["error"] == {
        "kind": "cancellation_timeout",
        "message": (
            "Active Module work did not stop before cancellation timeout"
        ),
        "retryable": False,
    }
    assert not any(event["type"] == "run_cancelled" for event in events)
    assert timed_out_manifest["status"] == "failed"
    assert timed_out_manifest["failures"][-1]["kind"] == "cancellation_timeout"
    assert still_excluded.status_code == 409
    assert later.status_code == 200
    assert later_run_id != run_id
    assert later_events[-1]["type"] == "run_completed"
    assert later_manifest["status"] == "completed"
