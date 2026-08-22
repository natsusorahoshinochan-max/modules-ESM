"""Public-protocol acceptance for v2 Run cancellation and derivation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from core.operation import (
    BindingEnvironment,
    ReadinessResult,
)
from core.execution.results import ProjectReplayIndex, ReplayIndexEntry
from core.project.objects import ProjectObjectStore
from core.execution.node_attempt import (
    ExecutionTermination,
)
from core.execution.ledger import FilesystemLedgerStore
from protein_workbench_public.bootstrap import create_application
from tests.support.protocol import validate_error, validate_response
from protein_workbench_public.ledger_codec import encode_event
from tests.fixtures.public_v2 import wait_for_testclient_run_terminal
from tests.test_run_runtime import (
    _artifact_catalog,
    _commit_artifact_node,
    _commit_independent_nodes,
    _commit_one_node,
    _commit_pipeline,
    _direct_catalog,
    _pipeline_catalog,
)


def _start(
    client: TestClient,
    project_id: str,
    committed: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_commit_id": committed["workflow_commit_id"],
            "client_request_id": request_id,
        },
    )
    assert response.status_code == 202
    validate_response("start_run", 202, response.json())
    return response.json()


def _wait_terminal(
    client: TestClient,
    project_id: str,
    run_id: str,
) -> dict[str, Any]:
    return wait_for_testclient_run_terminal(client, project_id, run_id)


def _public_events(
    app: Any,
    project_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    runtime = app.state.run_runtime
    return [
        encode_event(
            project_id=project_id,
            run_id=run_id,
            fact=fact,
        )["event"]
        for fact in runtime.events(project_id, run_id)
    ]


def _terminal_ids(events: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        "node_attempt_ids": {
            event["node_attempt_id"]
            for event in events
            if event["type"] == "node_attempt_started"
        },
        "operation_attempt_ids": {
            event["operation_attempt_id"]
            for event in events
            if event["type"] == "operation_attempt_started"
        },
        "invocation_ids": {
            event["invocation_id"]
            for event in events
            if event["type"] == "engine_invocation_started"
        },
    }


class _PublishConclusionThenLoseAcknowledgement:
    def __init__(self, *, publish_final_name: bool) -> None:
        self.filesystem = FilesystemLedgerStore()
        self.publish_final_name = publish_final_name
        self.conclusion_published = threading.Event()
        self.release_acknowledgement = threading.Event()
        self.conclusion_publication_attempts = 0

    def read_transactions(self, *, root, relative_parts):
        return self.filesystem.read_transactions(
            root=root,
            relative_parts=relative_parts,
        )

    def publish(self, *, root, relative_parts, payload) -> None:
        transaction = json.loads(payload)
        is_conclusion = any(
            fact["fact_type"] == "outputs_published"
            for fact in transaction["facts"]
        )
        if not is_conclusion or self.publish_final_name:
            self.filesystem.publish(
                root=root,
                relative_parts=relative_parts,
                payload=payload,
            )
        if is_conclusion:
            self.conclusion_publication_attempts += 1
            self.conclusion_published.set()
            assert self.release_acknowledgement.wait(timeout=2)
            raise OSError("fixture conclusion acknowledgement failure")


@pytest.mark.parametrize("publish_final_name", (False, True))
def test_finished_worker_exposes_sticky_unavailable_evidence(
    tmp_path,
    monkeypatch,
    publish_final_name: bool,
) -> None:
    store = _PublishConclusionThenLoseAcknowledgement(
        publish_final_name=publish_final_name,
    )
    project_root = tmp_path / "projects"
    run_root = tmp_path / "runs"
    output_root = tmp_path / "outputs"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(run_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("PROTEIN_WORKBENCH_CACHE_ROOT", str(cache_root))
    app = create_application(
        frozen_catalog_override=_direct_catalog([], cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
        _v2_ledger_transaction_store=store,
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(
            client,
            project_id,
            committed,
            "unacknowledged-conclusion",
        )
        assert store.conclusion_published.is_set()
        store.release_acknowledgement.set()
        app.state.run_runtime.shutdown()

        projection = client.get(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}"
        )
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        with client.websocket_connect(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}/events"
        ) as websocket:
            unavailable_event_stream = websocket.receive_json()
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_json()

    assert projection.status_code == cancelled.status_code == 503
    projection_details = projection.json()["error"]["details"]
    for response in (projection, cancelled):
        validate_error(response.json(), status=503)
        assert response.json()["error"]["code"] == "evidence_unavailable"
        assert response.json()["error"]["details"] == projection_details
    validate_error(unavailable_event_stream, status=503)
    assert unavailable_event_stream["error"]["code"] == (
        "evidence_unavailable"
    )
    assert unavailable_event_stream["error"]["details"] == projection_details
    assert closed.value.code == 1008
    durable_transactions = [
        json.loads(path.read_bytes())
        for path in sorted(
            (run_root / project_id / receipt["run_id"] / "ledger").glob(
                "*.json"
            )
        )
    ]
    conclusions = [
        transaction
        for transaction in durable_transactions
        if any(
            fact["fact_type"] == "outputs_published"
            for fact in transaction["facts"]
        )
    ]
    assert bool(conclusions) is publish_final_name
    if conclusions:
        assert [
            fact["fact_type"] for fact in conclusions[0]["facts"]
        ][-3:] == [
            "outputs_published",
            "node_attempt_terminal",
            "node_disposition",
        ]
        assert conclusions[0]["facts"][-2]["payload"]["status"] == (
            "succeeded"
        )
    assert store.conclusion_publication_attempts == 1
    assert list(output_root.rglob("objects/v1/sha256/*/*"))
    assert not list(cache_root.rglob("*.json"))


@pytest.mark.deterministic_acceptance
def test_cancel_during_operation_is_idempotent_and_closes_active_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            execution_gate=(entered, release),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-active")
        assert entered.wait(timeout=2)

        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={"reason": "operator requested cancellation"},
        )
        repeated = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        release.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    validate_response("cancel_run", 200, cancelled.json())
    assert cancelled.json()["outcome"] == "cancellation_requested"
    assert repeated.json() == {
        **cancelled.json(),
        "outcome": "already_requested",
    }
    assert projection["status"] == "cancelled"
    assert projection["outputs"] == []
    assert projection["node_dispositions"] == [
        {
            "node_id": "direct",
            "outcome": "cancelled",
            "blocked_by": [],
            "terminal_sequence": projection["node_dispositions"][0][
                "terminal_sequence"
            ],
        }
    ]
    events = _public_events(app, project_id, receipt["run_id"])
    terminals = [
        (event["type"], event["status"])
        for event in events
        if event["type"]
        in {
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }
    ]
    assert terminals == [
        ("engine_invocation_terminal", "succeeded"),
        ("operation_attempt_terminal", "cancelled"),
        ("node_attempt_terminal", "cancelled"),
    ]


def test_cancel_before_schedule_disposes_every_node_without_attempts(
    tmp_path,
    monkeypatch,
) -> None:
    first_entered = threading.Event()
    first_release = threading.Event()
    calls: list[str] = []
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            execution_gate=(first_entered, first_release),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        first_project, first_committed = _commit_one_node(client)
        second_project, second_committed = _commit_independent_nodes(
            client,
            ("test.direct.local", "test.direct.local"),
        )
        first = _start(client, first_project, first_committed, "occupy-worker")
        assert first_entered.wait(timeout=2)
        queued = _start(client, second_project, second_committed, "cancel-queued")

        cancelled = client.post(
            f"/api/v2/projects/{second_project}/runs/{queued['run_id']}:cancel",
            json={},
        )
        first_release.set()
        _wait_terminal(client, first_project, first["run_id"])
        projection = _wait_terminal(client, second_project, queued["run_id"])

    assert cancelled.status_code == 200
    assert projection["status"] == "cancelled"
    assert {
        item["node_id"]: item["outcome"]
        for item in projection["node_dispositions"]
    } == {"direct-0": "cancelled", "direct-1": "cancelled"}
    events = _public_events(app, second_project, queued["run_id"])
    assert not any(
        event["type"].endswith("_attempt_started")
        or event["type"] == "engine_invocation_started"
        for event in events
    )


def test_completion_race_is_decided_by_the_ledger_cursor(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "complete-first")
        projection = _wait_terminal(client, project_id, receipt["run_id"])
        raced = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={"after_sequence": receipt["event_cursor"]},
        )
        observed_terminal = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={"after_sequence": projection["ledger_cursor"]},
        )

    assert raced.status_code == 200
    assert raced.json()["outcome"] == "completed_before_cancel"
    assert raced.json()["decision_sequence"] == projection["terminal_sequence"]
    assert observed_terminal.json()["outcome"] == "already_terminal"
    assert observed_terminal.json()["decision_sequence"] == (
        projection["terminal_sequence"]
    )


@pytest.mark.parametrize(
    ("first_error", "first_outcome", "expected_run_status"),
    (
        (RuntimeError("fixture Node failure"), "failed", "failed"),
        (
            ExecutionTermination("interrupted"),
            "interrupted",
            "interrupted",
        ),
    ),
)
def test_run_terminal_precedence_uses_durable_node_dispositions(
    tmp_path,
    monkeypatch,
    first_error: BaseException,
    first_outcome: str,
    expected_run_status: str,
) -> None:
    second_entered = threading.Event()
    second_release = threading.Event()

    def execute_by_node(resources) -> None:
        if resources.node_id == "direct-0":
            raise first_error
        second_entered.set()
        assert second_release.wait(timeout=2)

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_by_node,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_independent_nodes(
            client,
            ("test.direct.local", "test.direct.local"),
        )
        receipt = _start(
            client,
            project_id,
            committed,
            f"{expected_run_status}-before-cancelled",
        )
        assert second_entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        second_release.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert cancelled.json()["outcome"] == "cancellation_requested"
    assert projection["status"] == expected_run_status
    assert {
        item["node_id"]: item["outcome"]
        for item in projection["node_dispositions"]
    } == {"direct-0": first_outcome, "direct-1": "cancelled"}


def test_cancel_during_cache_lookup_closes_only_the_node_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()
    original_lookup = ProjectReplayIndex.lookup

    def blocking_lookup(
        replay_index: ProjectReplayIndex,
        project_id: str,
        result_identity: str,
    ) -> ReplayIndexEntry | None:
        entered.set()
        assert release.wait(timeout=2)
        return original_lookup(replay_index, project_id, result_identity)

    monkeypatch.setattr(ProjectReplayIndex, "lookup", blocking_lookup)
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(calls, cacheable=True),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-cache-lookup")
        assert entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        release.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert projection["status"] == "cancelled"
    assert calls == []
    fact_types = [
        event["type"]
        for event in _public_events(app, project_id, receipt["run_id"])
    ]
    assert fact_types.count("node_attempt_started") == 1
    assert fact_types.count("node_attempt_terminal") == 1
    assert "readiness_attested" not in fact_types
    assert "operation_attempt_started" not in fact_types
    assert "engine_invocation_started" not in fact_types


def test_cancel_during_readiness_closes_only_the_node_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    def hold_readiness(_check_input: BindingEnvironment) -> ReadinessResult:
        entered.set()
        assert release.wait(timeout=2)
        return ReadinessResult(True)

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            calls,
            readiness_checks={"test.direct.local": hold_readiness},
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-readiness")
        assert entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        release.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert projection["status"] == "cancelled"
    assert calls == []
    fact_types = [
        event["type"]
        for event in _public_events(app, project_id, receipt["run_id"])
    ]
    assert fact_types.count("node_attempt_started") == 1
    assert fact_types.count("node_attempt_terminal") == 1
    assert fact_types.count("readiness_attested") == 1
    assert "operation_attempt_started" not in fact_types
    assert "engine_invocation_started" not in fact_types


def test_retry_after_failure_creates_new_evidence_without_mutating_source(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()
    catalog = _direct_catalog(
        calls,
        cacheable=True,
        execution_gate=(entered, release),
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        source = _start(client, project_id, committed, "source-failure")
        assert entered.wait(timeout=2)
        source_projection = _wait_terminal(client, project_id, source["run_id"])
        assert source_projection["status"] == "failed"
        source_events = _public_events(app, project_id, source["run_id"])
        source_bytes = json.dumps(source_events, sort_keys=True)

        release.set()
        derived_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "policy": "retry_failed",
                "node_ids": ["direct"],
                "client_request_id": "retry-source-failure",
            },
        )
        assert derived_response.status_code == 202
        derived = derived_response.json()
        derived_projection = _wait_terminal(
            client,
            project_id,
            derived["run_id"],
        )

    assert derived["run_id"] != source["run_id"]
    assert derived_projection["status"] == "succeeded"
    assert derived_projection["derived_from_run_id"] == source["run_id"]
    assert json.dumps(
        _public_events(app, project_id, source["run_id"]),
        sort_keys=True,
    ) == source_bytes
    assert calls.count("execute:test.direct.local") == 2
    assert [
        item["resolution"]
        for item in derived_projection["node_dispositions"]
    ] == ["executed"]
    derived_events = _public_events(app, project_id, derived["run_id"])
    for identity_kind, source_ids in _terminal_ids(source_events).items():
        assert source_ids.isdisjoint(
            _terminal_ids(derived_events)[identity_kind]
        )
    assert any(
        event["type"] == "readiness_attested"
        for event in derived_events
    )


def test_force_recompute_executes_selected_node_and_reuses_only_typed_results(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    catalog = _direct_catalog(calls, cacheable=True)
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=catalog,
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_independent_nodes(
            client,
            ("test.direct.local", "test.direct.local"),
        )
        source = _start(client, project_id, committed, "source-success")
        source_projection = _wait_terminal(client, project_id, source["run_id"])
        source_events = _public_events(app, project_id, source["run_id"])

        forced_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "policy": "force_selected",
                "node_ids": ["direct-0"],
                "client_request_id": "force-one-node",
            },
        )
        assert forced_response.status_code == 202
        forced = forced_response.json()
        forced_projection = _wait_terminal(
            client,
            project_id,
            forced["run_id"],
        )

    assert source_projection["status"] == "succeeded"
    assert forced_projection["status"] == "succeeded"
    assert forced_projection["derived_from_run_id"] == source["run_id"]
    assert {
        item["node_id"]: item["resolution"]
        for item in forced_projection["node_dispositions"]
    } == {
        "direct-0": "executed",
        "direct-1": "cache_replayed",
    }
    forced_events = _public_events(app, project_id, forced["run_id"])
    replayed_attempt = next(
        event["node_attempt_id"]
        for event in forced_events
        if event["type"] == "node_attempt_started"
        and event["node_id"] == "direct-1"
    )
    assert not any(
        event["type"] == "operation_attempt_started"
        and event["node_attempt_id"] == replayed_attempt
        for event in forced_events
    )
    for identity_kind, source_ids in _terminal_ids(source_events).items():
        assert source_ids.isdisjoint(
            _terminal_ids(forced_events)[identity_kind]
        )


def test_force_recompute_bypasses_the_selected_downstream_closure(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    catalog = _pipeline_catalog(calls, cacheable=True)
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=catalog,
    )

    with TestClient(app) as client:
        project_id, committed = _commit_pipeline(client)
        source = _start(client, project_id, committed, "force-source")
        assert _wait_terminal(
            client,
            project_id,
            source["run_id"],
        )["status"] == "succeeded"
        calls.clear()
        forced_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "policy": "force_selected",
                "node_ids": ["source"],
                "client_request_id": "force-source-closure",
            },
        )
        assert forced_response.status_code == 202
        forced = forced_response.json()
        projection = _wait_terminal(client, project_id, forced["run_id"])

    assert projection["status"] == "succeeded"
    assert "execute:source" in calls
    assert "sink-input:ready" in calls
    assert projection["derived_from_run_id"] == source["run_id"]


def test_cancel_terminates_registered_process_group_children_and_temp_work(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    process_ids = tmp_path / "process-ids"

    def execute_in_process_group(resources) -> None:
        with resources.temporary_directory(prefix="cancel-process") as workspace:
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os,pathlib,signal,subprocess,sys,time;"
                        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                        "child=subprocess.Popen([sys.executable,'-c',"
                        "'import signal,time;"
                        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                        "time.sleep(30)']);"
                        "pathlib.Path(sys.argv[1]).write_text("
                        "f'{os.getpid()} {child.pid}');"
                        "time.sleep(30)"
                    ),
                    str(process_ids),
                ],
                start_new_session=True,
            )
            deadline = time.monotonic() + 2
            while not process_ids.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert process_ids.exists()
            (workspace / "private-work").write_text("temporary")
            with resources.cancellable_process_group(os.getpgid(worker.pid)):
                entered.set()
                worker.wait(timeout=5)

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_in_process_group,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-process-group")
        assert entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert projection["status"] == "cancelled"
    parent_pid, child_pid = (
        int(value) for value in process_ids.read_text().split()
    )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if all(
            subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                check=False,
                capture_output=True,
                text=True,
            ).stdout.strip()
            in {"", "Z"}
            for pid in (parent_pid, child_pid)
        ):
            break
        time.sleep(0.02)
    assert all(
        subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        in {"", "Z"}
        for pid in (parent_pid, child_pid)
    )
    temp_node_root = (
        tmp_path
        / "projects"
        / project_id
        / "runs"
        / receipt["run_id"]
        / "temp"
        / "direct"
    )
    assert not temp_node_root.exists()


def test_process_group_registered_after_cancel_uses_full_cleanup_protocol(
    tmp_path,
    monkeypatch,
) -> None:
    spawned = threading.Event()
    allow_registration = threading.Event()
    worker_pid: dict[str, int] = {}

    def register_after_cancel(resources) -> None:
        worker = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import signal,time;"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                    "time.sleep(30)"
                ),
            ],
            start_new_session=True,
        )
        worker_pid["value"] = worker.pid
        spawned.set()
        assert allow_registration.wait(timeout=3)
        with resources.cancellable_process_group(os.getpgid(worker.pid)):
            worker.wait(timeout=5)

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=register_after_cancel,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-late-group")
        assert spawned.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        allow_registration.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert projection["status"] == "cancelled"
    process_status = subprocess.run(
        ["ps", "-p", str(worker_pid["value"]), "-o", "stat="],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert process_status in {"", "Z"}


def test_successful_process_fallback_is_confirmed_when_context_exits(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    fallback_called = threading.Event()

    def finish_fallback() -> None:
        fallback_called.set()
        release.set()

    def execute_with_fallback(resources) -> None:
        with resources.cancellable_process_group(
            os.getpgrp(),
            fallback=finish_fallback,
        ):
            entered.set()
            assert release.wait(timeout=3)

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_with_fallback,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-fallback")
        assert entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert fallback_called.is_set()
    assert projection["status"] == "cancelled"


def test_cancel_during_factory_closes_started_node_before_operation_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def hold_factory(resources) -> None:
        del resources
        entered.set()
        assert release.wait(timeout=3)

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            factory_action=hold_factory,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-during-factory")
        assert entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        release.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert cancelled.json()["outcome"] == "cancellation_requested"
    assert projection["status"] == "cancelled"
    assert projection["node_dispositions"][0]["outcome"] == "cancelled"
    events = _public_events(app, project_id, receipt["run_id"])
    event_types = [event["type"] for event in events]
    assert event_types.count("node_attempt_started") == 1
    assert event_types.count("node_attempt_terminal") == 1
    assert "operation_attempt_started" not in event_types
    assert "engine_invocation_started" not in event_types


def test_cancel_factory_cleanup_failure_interrupts_started_node_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def hold_factory(resources) -> None:
        del resources
        entered.set()
        assert release.wait(timeout=3)

    def fail_cleanup(resources) -> None:
        del resources
        raise PermissionError("private-cleanup-detail")

    monkeypatch.setattr(
        "core.execution.resources.RunResources.cleanup_temporary_work",
        fail_cleanup,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            factory_action=hold_factory,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-factory")
        assert entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        release.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert projection["status"] == "interrupted"
    assert projection["node_dispositions"][0]["outcome"] == "interrupted"
    events = _public_events(app, project_id, receipt["run_id"])
    event_types = [event["type"] for event in events]
    assert event_types.count("node_attempt_started") == 1
    assert event_types.count("node_attempt_terminal") == 1
    assert "operation_attempt_started" not in event_types
    assert "engine_invocation_started" not in event_types
    assert "private-cleanup-detail" not in json.dumps(events)


def test_cancel_during_artifact_materialization_keeps_object_unpublished(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    original_store = ProjectObjectStore.store

    def hold_artifact_object(store, project_id, payload):
        stored = original_store(store, project_id, payload)
        if payload == b"MODEL        1\nEND\n":
            entered.set()
            assert release.wait(timeout=3)
        return stored

    monkeypatch.setattr(
        ProjectObjectStore,
        "store",
        hold_artifact_object,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(frozen_catalog_override=_artifact_catalog([]))

    with TestClient(app) as client:
        project_id, committed = _commit_artifact_node(client)
        receipt = _start(client, project_id, committed, "cancel-artifact")
        assert entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        release.set()
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    assert projection["status"] == "cancelled"
    assert projection["artifact_index"] == []
    assert projection["outputs"] == []
    events = _public_events(app, project_id, receipt["run_id"])
    assert not any(
        event["type"] == "node_disposition"
        and event["disposition"]["outcome"] == "succeeded"
        for event in events
    )
    objects = list(
        (tmp_path / "outputs" / project_id / "objects").rglob("*")
    )
    assert any(path.is_file() for path in objects)
    assert not list((tmp_path / "outputs").rglob("published/*"))


def test_normal_temp_cleanup_failure_does_not_publish_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    def fail_cleanup(resources) -> None:
        del resources
        raise PermissionError("private-normal-cleanup-detail")

    monkeypatch.setattr(
        "core.execution.resources.RunResources.cleanup_temporary_work",
        fail_cleanup,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(frozen_catalog_override=_artifact_catalog([]))

    with TestClient(app) as client:
        project_id, committed = _commit_artifact_node(client)
        receipt = _start(client, project_id, committed, "cleanup-artifact")
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert projection["status"] == "failed"
    assert projection["artifact_index"] == []
    assert projection["outputs"] == []
    retained = json.dumps(_public_events(app, project_id, receipt["run_id"]))
    assert "private-normal-cleanup-detail" not in retained
    assert not list(
        (tmp_path / "outputs" / project_id).rglob(
            "objects/v1/sha256/*/*"
        )
    )


def test_one_process_cleanup_failure_does_not_skip_other_process_groups(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    worker_pid: dict[str, int] = {}

    def fail_fallback() -> None:
        raise PermissionError("private-fallback-detail")

    def execute_with_two_groups(resources) -> None:
        worker = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            start_new_session=True,
        )
        worker_pid["value"] = worker.pid
        with resources.cancellable_process_group(
            os.getpgrp(),
            fallback=fail_fallback,
        ):
            with resources.cancellable_process_group(
                os.getpgid(worker.pid),
            ):
                entered.set()
                worker.wait(timeout=5)

    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_with_two_groups,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        receipt = _start(client, project_id, committed, "cancel-two-groups")
        assert entered.wait(timeout=2)
        cancelled = client.post(
            f"/api/v2/projects/{project_id}/runs/{receipt['run_id']}:cancel",
            json={},
        )
        projection = _wait_terminal(client, project_id, receipt["run_id"])

    assert cancelled.status_code == 200
    validate_response("cancel_run", 200, cancelled.json())
    assert projection["status"] == "failed"
    process_status = subprocess.run(
        ["ps", "-p", str(worker_pid["value"]), "-o", "stat="],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert process_status in {"", "Z"}
    retained = json.dumps(_public_events(app, project_id, receipt["run_id"]))
    assert "private-fallback-detail" not in retained


@pytest.mark.deterministic_acceptance
def test_cancel_and_derive_reject_cross_project_scope_with_shared_errors(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration={
            ("test.direct.local", "2.1.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        owner_project, owner_committed = _commit_one_node(client)
        other_project, _ = _commit_one_node(client)
        source = _start(client, owner_project, owner_committed, "scope-source")
        _wait_terminal(client, owner_project, source["run_id"])

        cancel = client.post(
            f"/api/v2/projects/{other_project}/runs/{source['run_id']}:cancel",
            json={},
        )
        derive = client.post(
            f"/api/v2/projects/{other_project}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "policy": "force_selected",
                "node_ids": ["direct"],
                "client_request_id": "cross-scope-derive",
            },
        )

    assert cancel.status_code == derive.status_code == 404
    assert cancel.json()["error"]["code"] == "cross_scope_access_denied"
    assert derive.json()["error"]["code"] == "cross_scope_access_denied"
    assert cancel.json()["error"]["details"] == derive.json()["error"]["details"]


def test_derived_artifacts_and_source_run_remain_independently_immutable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_application(frozen_catalog_override=_artifact_catalog([]))

    with TestClient(app) as client:
        project_id, committed = _commit_artifact_node(client)
        source = _start(client, project_id, committed, "artifact-source")
        source_projection = _wait_terminal(client, project_id, source["run_id"])
        source_artifact = source_projection["artifact_index"][0]
        source_download = client.get(
            f"/api/v2/projects/{project_id}/runs/{source['run_id']}/"
            f"artifacts/{source_artifact['artifact_reference']}"
        )
        source_events = _public_events(app, project_id, source["run_id"])

        derived_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "policy": "force_selected",
                "node_ids": ["artifact"],
                "client_request_id": "artifact-derived",
            },
        )
        assert derived_response.status_code == 202
        derived = derived_response.json()
        derived_projection = _wait_terminal(
            client,
            project_id,
            derived["run_id"],
        )
        source_after = client.get(
            f"/api/v2/projects/{project_id}/runs/{source['run_id']}"
        ).json()
        source_download_after = client.get(
            f"/api/v2/projects/{project_id}/runs/{source['run_id']}/"
            f"artifacts/{source_artifact['artifact_reference']}"
        )

    assert source_after == source_projection
    assert _public_events(app, project_id, source["run_id"]) == source_events
    assert source_download_after.content == source_download.content
    assert derived_projection["derived_from_run_id"] == source["run_id"]
    assert derived_projection["artifact_index"][0]["artifact_reference"] != (
        source_artifact["artifact_reference"]
    )


def test_derived_run_reuses_the_source_execution_plan_without_recompiling(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    environment = {
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    app = create_application(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration=environment,
    )

    with TestClient(app) as client:
        project_id, committed = _commit_one_node(client)
        source = _start(client, project_id, committed, "retained-plan-source")
        assert _wait_terminal(
            client,
            project_id,
            source["run_id"],
        )["status"] == "succeeded"
        current_draft = client.get(
            f"/api/v2/projects/{project_id}/workflow/draft"
        ).json()
        revised_workflow = {
            **current_draft["workflow"],
            "nodes": [
                {
                    **current_draft["workflow"]["nodes"][0],
                    "node_id": "replacement",
                }
            ],
        }
        revised = client.post(
            f"/api/v2/projects/{project_id}/workflow:commit",
            json={
                "workflow": revised_workflow,
            },
        )
        assert revised.status_code == 200
        assert revised.json()["workflow_commit_revision"] == 2
        assert revised.json()["workflow_commit_id"] != (
            committed["workflow_commit_id"]
        )

        def forbid_workflow_resolution(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(
                "Derived Run must reuse the source ExecutionPlan"
            )

        monkeypatch.setattr(
            app.state.workflow_authoring,
            "load_draft",
            forbid_workflow_resolution,
        )
        monkeypatch.setattr(
            app.state.workflow_authoring,
            "load_active_commit",
            forbid_workflow_resolution,
        )
        monkeypatch.setattr(
            app.state.workflow_authoring,
            "require_verified_commit",
            forbid_workflow_resolution,
        )
        derived_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "policy": "force_selected",
                "node_ids": ["direct"],
                "client_request_id": "retained-plan-derived",
            },
        )
        assert derived_response.status_code == 202
        projection = _wait_terminal(
            client,
            project_id,
            derived_response.json()["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert projection["derived_from_run_id"] == source["run_id"]


def test_terminal_source_without_its_retained_plan_fails_closed_after_restart(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    environment = {
        ("test.direct.local", "2.1.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    first_app = create_application(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration=environment,
    )

    with TestClient(first_app) as first_client:
        project_id, committed = _commit_one_node(first_client)
        source = _start(
            first_client,
            project_id,
            committed,
            "restart-source",
        )
        assert _wait_terminal(
            first_client,
            project_id,
            source["run_id"],
        )["status"] == "succeeded"

    restarted_app = create_application(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration=environment,
    )
    with TestClient(restarted_app) as restarted_client:
        derived_response = restarted_client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "policy": "force_selected",
                "node_ids": ["direct"],
                "client_request_id": "restart-derived",
            },
        )

    assert derived_response.status_code == 422
    assert derived_response.json()["error"]["code"] == "compile_rejected"
    assert derived_response.json()["error"]["details"]["issues"] == [
        {
            "code": "source_execution_plan_unavailable",
            "severity": "error",
            "message": (
                "Derived Run requires the exact in-memory Execution Plan "
                "retained by its source Run"
            ),
            "field_path": ["source_run_id"],
        }
    ]
