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
    validate_typed_value_response,
)


TERMINAL_WAIT_SECONDS = 5.0
_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "interrupted"}


def retrieve_typed_output_canonical_bytes(
    client: TestClient,
    project_id: str,
    run_id: str,
    output: dict[str, Any],
    value_index: int,
) -> bytes:
    """Retrieve and validate one exact canonical public Typed Output value."""
    prepared = prepare_rest_request(
        "typed_value_retrieval",
        {
            "project_id": project_id,
            "run_id": run_id,
            "node_id": output["node_id"],
            "output_port": output["output_port"],
            "value_index": value_index,
        },
    )
    response = client.request(prepared.method, prepared.route)
    assert response.status_code == 200
    metadata = {
        "typed_value": {
            "node_id": output["node_id"],
            "output_port": output["output_port"],
            "port_type": output["port_type"],
            "port_content_digest": output["content_digest"],
            "value_manifest_reference": output[
                "value_manifest_reference"
            ],
            "value_index": value_index,
            "value_count": output["value_count"],
            "value_content_digest": response.headers["digest"],
            "size": len(response.content),
        }
    }
    validate_typed_value_response(
        metadata,
        response.headers,
        response.content,
    )
    return response.content


def retrieve_typed_output_values(
    client: TestClient,
    project_id: str,
    run_id: str,
    output: dict[str, Any],
) -> list[Any]:
    """Decode public canonical envelopes after exact retrieval validation."""
    return [
        json.loads(
            retrieve_typed_output_canonical_bytes(
                client,
                project_id,
                run_id,
                output,
                value_index,
            )
        )["value"]
        for value_index in range(output["value_count"])
    ]


def retrieve_service_typed_output_canonical_bytes(
    service: Any,
    projection: dict[str, Any],
    output: dict[str, Any],
    value_index: int,
) -> bytes:
    """Retrieve one canonical value through the service public behavior seam."""
    _, payload = service.typed_value(
        projection["project_id"],
        projection["run_id"],
        output["node_id"],
        output["output_port"],
        value_index,
    )
    return payload


def decode_service_typed_output_value(
    service: Any,
    catalog: Any,
    projection: dict[str, Any],
    output: dict[str, Any],
    value_index: int = 0,
) -> Any:
    """Decode exact retrieved bytes through the descriptor's registered codec."""
    reference = output["port_type"]
    port_type = catalog.require_port_type(
        reference["contract_id"],
        reference["contract_version"],
    )
    return port_type.decode(
        retrieve_service_typed_output_canonical_bytes(
            service,
            projection,
            output,
            value_index,
        )
    )


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
        _, after_sequence, terminal = service.wait_for_events(
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
    service = client.app.state.run_runtime
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
