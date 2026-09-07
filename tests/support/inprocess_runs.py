"""Synchronize TestClient journeys on the durable runtime terminal."""

from __future__ import annotations
from typing import Any
from fastapi.testclient import TestClient
from tests.support.public_runs import PublicRunClient, TERMINAL_STATUSES
from tests.support.runtime_results import (
    TERMINAL_WAIT_SECONDS,
    wait_for_service_run_terminal_events,
)


def wait_for_testclient_run_terminal(
    client: TestClient,
    project_id: str,
    run_id: str,
    timeout_seconds: float = TERMINAL_WAIT_SECONDS,
) -> dict[str, Any]:
    """Wait on the durable ledger, then read the public terminal projection."""
    service = client.app.state.run_runtime
    wait_for_service_run_terminal_events(
        service,
        project_id,
        run_id,
        timeout_seconds,
    )
    projection = PublicRunClient(client).request(
        "run_projection",
        {"project_id": project_id, "run_id": run_id},
        expected_status=200,
    )
    if projection["status"] not in TERMINAL_STATUSES:
        raise AssertionError("durable terminal produced a non-terminal projection")
    return projection


def run_committed_workflow(
    client: TestClient,
    project_id: str,
    *,
    workflow_commit_id: str,
    request_id: str,
    timeout_seconds: float = TERMINAL_WAIT_SECONDS,
) -> dict[str, Any]:
    """Execute an already committed Workflow and return its terminal projection."""
    started = PublicRunClient(client).start_run(
        project_id,
        workflow_commit_id,
        request_id=request_id,
    )
    return wait_for_testclient_run_terminal(
        client,
        project_id,
        started["run_id"],
        timeout_seconds=timeout_seconds,
    )
