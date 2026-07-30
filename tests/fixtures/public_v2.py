"""Deterministic terminal waits for asynchronous public v2 Run journeys."""

from __future__ import annotations

from collections.abc import Callable
import json
import time
from typing import Any

from fastapi.testclient import TestClient
from websockets.sync.client import connect

from protein_workbench_public import (
    prepare_rest_request,
    prepare_run_event_stream_request,
    validate_event,
    validate_response,
)


TERMINAL_WAIT_SECONDS = 5.0
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}


def wait_for_service_run_terminal_events(
    service: Any,
    project_id: str,
    run_id: str,
    timeout_seconds: float = TERMINAL_WAIT_SECONDS,
) -> None:
    """Wait until the durable public event ledger records Run termination."""
    deadline = time.monotonic() + timeout_seconds
    after_sequence = 0
    terminal = False
    while not terminal:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError("public Run did not reach a durable terminal")
        _, after_sequence, terminal = service.wait_for_public_events(
            project_id,
            run_id,
            after_sequence,
            timeout_seconds=remaining,
        )


def wait_for_testclient_run_terminal(
    client: TestClient,
    project_id: str,
    run_id: str,
    timeout_seconds: float = TERMINAL_WAIT_SECONDS,
) -> dict[str, Any]:
    """Wait on the durable ledger, then read the public terminal projection."""
    service = client.app.state.run_execution_v2
    wait_for_service_run_terminal_events(
        service,
        project_id,
        run_id,
        timeout_seconds,
    )
    prepared = prepare_rest_request(
        "run_projection",
        {"project_id": project_id, "run_id": run_id},
    )
    response = client.request(
        prepared.method,
        prepared.route,
        json=prepared.json_body,
    )
    assert response.status_code == 200
    projection = response.json()
    validate_response("run_projection", 200, projection)
    if projection["status"] not in _TERMINAL_STATUSES:
        raise AssertionError("durable terminal produced a non-terminal projection")
    return projection


def wait_for_network_run_terminal(
    *,
    websocket_origin: str,
    project_id: str,
    run_id: str,
    fetch_projection: Callable[[], dict[str, Any]],
    timeout_seconds: float = TERMINAL_WAIT_SECONDS,
) -> dict[str, Any]:
    """Wait through the public event stream, then fetch its projection."""
    deadline = time.monotonic() + timeout_seconds
    stream = prepare_run_event_stream_request(
        {"project_id": project_id, "run_id": run_id}
    )
    terminal_status: str | None = None
    with connect(
        f"{websocket_origin}{stream.route}",
        open_timeout=timeout_seconds,
        close_timeout=timeout_seconds,
    ) as websocket:
        while terminal_status is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(
                    "public Run event stream did not reach a terminal"
                )
            message = json.loads(websocket.recv(timeout=remaining))
            validate_event(message)
            if message["event"]["type"] == "run_terminal":
                terminal_status = message["event"]["status"]
    projection = fetch_projection()
    if (
        projection["status"] != terminal_status
        or projection["status"] not in _TERMINAL_STATUSES
    ):
        raise AssertionError(
            "public terminal event and Run projection do not agree"
        )
    return projection
