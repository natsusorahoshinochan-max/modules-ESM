"""Public in-process journey execution and exact output retrieval.

The caller owns the application and expected outcome. These operations return
failed and cancelled runs unchanged and never select or replace a Provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from protein_workbench_public.workflow_codec import decode_workflow_document
from tests.support import inprocess_runs
from tests.support.public_runs import PublicRunClient


@dataclass(frozen=True, slots=True)
class PublicJourneyRun:
    workflow_commit_id: str
    projection: dict[str, Any]
    events: tuple[dict[str, Any], ...]


def commit_and_run(
    client: TestClient,
    project_id: str,
    workflow: dict[str, object],
    *,
    request_id: str,
    timeout_seconds: float = 5.0,
) -> PublicJourneyRun:
    decode_workflow_document(workflow)
    committed = PublicRunClient(client).commit_workflow(project_id, workflow)
    return run_committed_workflow(
        client,
        project_id,
        committed["workflow_commit_id"],
        request_id=request_id,
        timeout_seconds=timeout_seconds,
    )


def run_committed_workflow(
    client: TestClient,
    project_id: str,
    workflow_commit_id: str,
    *,
    request_id: str,
    timeout_seconds: float = 5.0,
) -> PublicJourneyRun:
    projection = inprocess_runs.run_committed_workflow(
        client,
        project_id,
        workflow_commit_id=workflow_commit_id,
        request_id=request_id,
        timeout_seconds=timeout_seconds,
    )
    run_id = projection["run_id"]
    events: list[dict[str, Any]] = []
    with client.websocket_connect(
        f"/api/v2/projects/{project_id}/runs/{run_id}/events"
    ) as websocket:
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"]["type"] == "run_terminal":
                break
    return PublicJourneyRun(workflow_commit_id, projection, tuple(events))


def _output(
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> dict[str, Any]:
    return next(
        output
        for output in projection["outputs"]
        if output["node_id"] == node_id
        and output["output_port"] == output_port
    )


def decode_one(
    client: TestClient,
    catalog: Any,
    projection: dict[str, Any],
    node_id: str,
    output_port: str,
) -> Any:
    output = _output(projection, node_id, output_port)
    assert output["value_count"] == 1
    port_type = catalog.require_port_type(
        output["port_type"]["contract_id"],
    )
    return port_type.decode(
        PublicRunClient(client).typed_output_bytes(
            projection["project_id"], projection["run_id"], output, 0
        )
    )
