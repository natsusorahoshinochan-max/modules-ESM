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

from core import ResultReplaySource
import core.run_execution_v2 as run_execution_v2
from core.server import create_app
from protein_workbench_public import validate_response
from tests.test_run_execution_v2 import (
    _artifact_catalog,
    _compile_artifact_node,
    _compile_independent_nodes,
    _compile_one_node,
    _compile_pipeline,
    _direct_catalog,
    _pipeline_catalog,
)


def _start(
    client: TestClient,
    project_id: str,
    compiled: dict[str, Any],
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "workflow_revision": compiled["workflow_revision"],
            "compile_id": compiled["compile_id"],
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
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v2/projects/{project_id}/runs/{run_id}"
        )
        assert response.status_code == 200
        projection = response.json()
        if projection["status"] not in {"admitted", "running"}:
            return projection
        time.sleep(0.01)
    raise AssertionError("Run did not reach a terminal projection")


def _facts(app: Any, project_id: str, run_id: str) -> list[dict[str, Any]]:
    record = app.state.run_execution_v2._require_record(project_id, run_id)
    return list(record.ledger.facts)


def _terminal_ids(facts: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        "node_attempt_ids": {
            fact["payload"]["node_attempt_id"]
            for fact in facts
            if fact["fact_type"] == "node_attempt_started"
        },
        "operation_attempt_ids": {
            fact["payload"]["operation_attempt_id"]
            for fact in facts
            if fact["fact_type"] == "operation_attempt_started"
        },
        "invocation_ids": {
            fact["payload"]["invocation_id"]
            for fact in facts
            if fact["fact_type"] == "engine_invocation_started"
        },
    }


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
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            execution_gate=(entered, release),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        receipt = _start(client, project_id, compiled, "cancel-active")
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
    facts = _facts(app, project_id, receipt["run_id"])
    terminals = [
        (fact["fact_type"], fact["payload"]["status"])
        for fact in facts
        if fact["fact_type"]
        in {
            "engine_invocation_terminal",
            "operation_attempt_terminal",
            "node_attempt_terminal",
        }
    ]
    assert terminals == [
        ("engine_invocation_terminal", "cancelled"),
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
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            execution_gate=(first_entered, first_release),
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        first_project, first_compiled = _compile_one_node(client)
        second_project, second_compiled = _compile_independent_nodes(
            client,
            ("test.direct.local", "test.direct.local"),
        )
        first = _start(client, first_project, first_compiled, "occupy-worker")
        assert first_entered.wait(timeout=2)
        queued = _start(client, second_project, second_compiled, "cancel-queued")

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
    facts = _facts(app, second_project, queued["run_id"])
    assert not any(
        fact["fact_type"].endswith("_attempt_started")
        or fact["fact_type"] == "engine_invocation_started"
        for fact in facts
    )


def test_completion_race_is_decided_by_the_ledger_cursor(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        receipt = _start(client, project_id, compiled, "complete-first")
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


class _ControllableReplay(ResultReplaySource):
    def __init__(self) -> None:
        self.enabled = False
        self.lookups: list[str] = []

    def lookup(self, *, node, **kwargs):
        del kwargs
        self.lookups.append(node.node_id)
        if self.enabled:
            return {"text": "REPLAYED"}
        return None


def test_retry_after_failure_creates_new_evidence_without_mutating_source(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()
    replay = _ControllableReplay()
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
            execution_gate=(entered, release),
        ),
        v2_result_replay_source=replay,
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        source = _start(client, project_id, compiled, "source-failure")
        assert entered.wait(timeout=2)
        source_projection = _wait_terminal(client, project_id, source["run_id"])
        assert source_projection["status"] == "failed"
        source_facts = _facts(app, project_id, source["run_id"])
        source_bytes = json.dumps(source_facts, sort_keys=True)

        replay.enabled = True
        release.set()
        derived_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "compile_id": compiled["compile_id"],
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
        _facts(app, project_id, source["run_id"]),
        sort_keys=True,
    ) == source_bytes
    assert replay.lookups == ["direct"]
    derived_facts = _facts(app, project_id, derived["run_id"])
    for identity_kind, source_ids in _terminal_ids(source_facts).items():
        assert source_ids.isdisjoint(_terminal_ids(derived_facts)[identity_kind])
    assert any(
        fact["fact_type"] == "readiness_attested"
        for fact in derived_facts
    )


def test_force_recompute_executes_selected_node_and_reuses_only_typed_results(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    replay = _ControllableReplay()
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            calls,
            cacheable=True,
        ),
        v2_result_replay_source=replay,
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_independent_nodes(
            client,
            ("test.direct.local", "test.direct.local"),
        )
        source = _start(client, project_id, compiled, "source-success")
        source_projection = _wait_terminal(client, project_id, source["run_id"])
        source_facts = _facts(app, project_id, source["run_id"])
        replay.enabled = True
        replay.lookups.clear()

        forced_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "compile_id": compiled["compile_id"],
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
    assert replay.lookups == ["direct-1"]
    assert {
        item["node_id"]: item["resolution"]
        for item in forced_projection["node_dispositions"]
    } == {
        "direct-0": "executed",
        "direct-1": "cache_replayed",
    }
    forced_facts = _facts(app, project_id, forced["run_id"])
    replayed_attempt = next(
        fact["payload"]["node_attempt_id"]
        for fact in forced_facts
        if fact["fact_type"] == "node_attempt_started"
        and fact["payload"]["node_id"] == "direct-1"
    )
    assert not any(
        fact["fact_type"] == "operation_attempt_started"
        and fact["payload"]["node_attempt_id"] == replayed_attempt
        for fact in forced_facts
    )
    for identity_kind, source_ids in _terminal_ids(source_facts).items():
        assert source_ids.isdisjoint(_terminal_ids(forced_facts)[identity_kind])


def test_force_recompute_bypasses_the_selected_downstream_closure(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    replay = _ControllableReplay()
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_pipeline_catalog(calls, cacheable=True),
        v2_result_replay_source=replay,
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_pipeline(client)
        source = _start(client, project_id, compiled, "force-source")
        assert _wait_terminal(
            client,
            project_id,
            source["run_id"],
        )["status"] == "succeeded"
        calls.clear()
        replay.enabled = True
        replay.lookups.clear()
        forced_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "compile_id": compiled["compile_id"],
                "policy": "force_selected",
                "node_ids": ["source"],
                "client_request_id": "force-source-closure",
            },
        )
        assert forced_response.status_code == 202
        forced = forced_response.json()
        projection = _wait_terminal(client, project_id, forced["run_id"])

    assert projection["status"] == "succeeded"
    assert replay.lookups == []
    assert "execute:source" in calls
    assert "sink-input:ready" in calls
    scope = _facts(app, project_id, forced["run_id"])[0]["payload"]
    assert scope["derived_from"] == {
        "source_run_id": source["run_id"],
        "policy": "force_selected",
        "selected_node_ids": ["source"],
        "forced_node_ids": ["source", "sink"],
    }


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
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_in_process_group,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        receipt = _start(client, project_id, compiled, "cancel-process-group")
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


def test_cancel_factory_cleanup_failure_is_interrupted_without_false_attempt(
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
        "core.run_execution_v2.RunResources.cleanup_temporary_work",
        fail_cleanup,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            factory_action=hold_factory,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        receipt = _start(client, project_id, compiled, "cancel-factory")
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
    facts = _facts(app, project_id, receipt["run_id"])
    assert not any(
        fact["fact_type"] in {
            "node_attempt_started",
            "operation_attempt_started",
            "engine_invocation_started",
        }
        for fact in facts
    )
    assert "private-cleanup-detail" not in json.dumps(facts)


def test_cancel_during_artifact_materialization_removes_uncommitted_files(
    tmp_path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    original_write = run_execution_v2.write_private_new_file

    def hold_published_artifact(
        root,
        relative_parts,
        payload,
        *,
        field,
    ):
        path = original_write(
            root,
            relative_parts,
            payload,
            field=field,
        )
        if (
            field == "artifact_path"
            and "published" in relative_parts
        ):
            entered.set()
            assert release.wait(timeout=3)
        return path

    monkeypatch.setattr(
        run_execution_v2,
        "write_private_new_file",
        hold_published_artifact,
    )
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(frozen_catalog_override=_artifact_catalog([]))

    with TestClient(app) as client:
        project_id, compiled = _compile_artifact_node(client)
        receipt = _start(client, project_id, compiled, "cancel-artifact")
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
    facts = _facts(app, project_id, receipt["run_id"])
    assert not any(
        fact["fact_type"] in {"artifact_published", "outputs_published"}
        for fact in facts
    )
    published_root = (
        tmp_path / "outputs" / project_id / receipt["run_id"] / "published"
    )
    assert not published_root.exists() or not any(published_root.iterdir())


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
    app = create_app(
        frozen_catalog_override=_direct_catalog(
            [],
            execution_action=execute_with_two_groups,
        ),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        project_id, compiled = _compile_one_node(client)
        receipt = _start(client, project_id, compiled, "cancel-two-groups")
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
    retained = json.dumps(_facts(app, project_id, receipt["run_id"]))
    assert "private-fallback-detail" not in retained


def test_cancel_and_derive_reject_cross_project_scope_with_shared_errors(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    app = create_app(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration={
            ("test.direct.local", "2.0.0"): {
                "values": {"credential": "credential-value"},
            }
        },
    )

    with TestClient(app) as client:
        owner_project, owner_compiled = _compile_one_node(client)
        other_project, other_compiled = _compile_one_node(client)
        source = _start(client, owner_project, owner_compiled, "scope-source")
        _wait_terminal(client, owner_project, source["run_id"])

        cancel = client.post(
            f"/api/v2/projects/{other_project}/runs/{source['run_id']}:cancel",
            json={},
        )
        derive = client.post(
            f"/api/v2/projects/{other_project}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "compile_id": other_compiled["compile_id"],
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
    app = create_app(frozen_catalog_override=_artifact_catalog([]))

    with TestClient(app) as client:
        project_id, compiled = _compile_artifact_node(client)
        source = _start(client, project_id, compiled, "artifact-source")
        source_projection = _wait_terminal(client, project_id, source["run_id"])
        source_artifact = source_projection["artifact_index"][0]
        source_download = client.get(
            f"/api/v2/projects/{project_id}/runs/{source['run_id']}/"
            f"artifacts/{source_artifact['artifact_reference']}"
        )
        source_facts = _facts(app, project_id, source["run_id"])

        derived_response = client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "compile_id": compiled["compile_id"],
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
    assert _facts(app, project_id, source["run_id"]) == source_facts
    assert source_download_after.content == source_download.content
    assert derived_projection["derived_from_run_id"] == source["run_id"]
    assert derived_projection["artifact_index"][0]["artifact_reference"] != (
        source_artifact["artifact_reference"]
    )


def test_terminal_source_can_be_derived_after_backend_restart(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROJECT_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("PROTEIN_WORKBENCH_OUTPUT_ROOT", str(tmp_path / "outputs"))
    environment = {
        ("test.direct.local", "2.0.0"): {
            "values": {"credential": "credential-value"},
        }
    }
    first_app = create_app(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration=environment,
    )

    with TestClient(first_app) as first_client:
        project_id, compiled = _compile_one_node(first_client)
        source = _start(
            first_client,
            project_id,
            compiled,
            "restart-source",
        )
        assert _wait_terminal(
            first_client,
            project_id,
            source["run_id"],
        )["status"] == "succeeded"

    restarted_app = create_app(
        frozen_catalog_override=_direct_catalog([]),
        v2_environment_configuration=environment,
    )
    with TestClient(restarted_app) as restarted_client:
        derived_response = restarted_client.post(
            f"/api/v2/projects/{project_id}/runs:derive",
            json={
                "source_run_id": source["run_id"],
                "compile_id": compiled["compile_id"],
                "policy": "force_selected",
                "node_ids": ["direct"],
                "client_request_id": "restart-derived",
            },
        )
        assert derived_response.status_code == 202
        derived = derived_response.json()
        projection = _wait_terminal(
            restarted_client,
            project_id,
            derived["run_id"],
        )

    assert projection["status"] == "succeeded"
    assert projection["derived_from_run_id"] == source["run_id"]
