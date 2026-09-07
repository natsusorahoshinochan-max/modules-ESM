"""Public Workflow/Run operations over a caller-owned HTTP client."""

from __future__ import annotations

import json
import time
from typing import Any
from collections.abc import Mapping
from websockets.sync.client import connect

import httpx

from tests.support.public_request import (
    encode_project_input_content,
    prepare_rest_request,
    prepare_run_event_stream_request,
)
from tests.support.protocol import (
    validate_artifact_response,
    validate_error,
    validate_event,
    validate_response,
    validate_typed_value_response,
)


TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


class PublicRunClient:
    """Exercise only operations and payloads declared by the v2 bundle."""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def request(
        self,
        operation_id: str,
        request_model: dict[str, Any],
        *,
        expected_status: int | None = None,
    ) -> dict[str, Any]:
        prepared = prepare_rest_request(operation_id, request_model)
        response = self._http.request(
            prepared.method,
            prepared.route,
            json=prepared.json_body,
        )
        if expected_status is not None:
            assert response.status_code == expected_status, response.text
        payload = response.json()
        validate_response(operation_id, response.status_code, payload)
        return payload

    def commit_workflow(
        self,
        project_id: str,
        workflow: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.request(
            "commit_project_workflow",
            {
                "project_id": project_id,
                "workflow": dict(workflow),
            },
            expected_status=200,
        )

    def start_run(
        self,
        project_id: str,
        workflow_commit_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        return self.request(
            "start_run",
            {
                "project_id": project_id,
                "workflow_commit_id": workflow_commit_id,
                "client_request_id": request_id,
            },
            expected_status=202,
        )

    def wait_terminal(
        self,
        project_id: str,
        run_id: str,
        *,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """Poll the public projection through the supplied HTTP transport."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            projection = self.request(
                "run_projection",
                {
                    "project_id": project_id,
                    "run_id": run_id,
                },
                expected_status=200,
            )
            if projection["status"] in TERMINAL_STATUSES:
                return projection
            time.sleep(0.02)
        raise AssertionError("public Run did not reach a terminal projection")

    def typed_output_bytes(
        self,
        project_id: str,
        run_id: str,
        output: dict[str, Any],
        value_index: int,
    ) -> bytes:
        """Retrieve one exact canonical value, including integrity validation."""
        _, body = self.typed_value(
            {
                "project_id": project_id,
                "run_id": run_id,
                "node_id": output["node_id"],
                "output_port": output["output_port"],
                "value_index": value_index,
            },
            output,
        )
        return body

    def typed_output_values(
        self,
        project_id: str,
        run_id: str,
        output: dict[str, Any],
    ) -> list[Any]:
        """Read ordered JSON envelope values without interpreting their science."""
        return [
            json.loads(
                self.typed_output_bytes(
                    project_id,
                    run_id,
                    output,
                    index,
                )
            )["value"]
            for index in range(output["value_count"])
        ]

    def create_project(self, name: str) -> dict[str, Any]:
        return self.request("create_project", {"name": name})

    def publish_project_input(
        self,
        project_id: str,
        *,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        return self.request(
            "publish_project_input",
            {
                "project_id": project_id,
                "filename": filename,
                "content_base64": encode_project_input_content(content),
            },
        )

    def project_input_metadata(
        self,
        project_id: str,
        project_input_ref: str,
    ) -> dict[str, Any]:
        return self.request(
            "project_input_metadata",
            {
                "project_id": project_id,
                "project_input_ref": project_input_ref,
            },
        )

    def artifact(
        self,
        request_model: dict[str, Any],
        metadata: dict[str, Any],
    ) -> bytes:
        prepared = prepare_rest_request("artifact_retrieval", request_model)
        response = self._http.request(prepared.method, prepared.route)
        if response.status_code != 200:
            validate_error(response.json(), status=response.status_code)
            raise AssertionError("structured artifact error validation returned")
        validate_artifact_response(metadata, response.headers, response.content)
        return response.content

    def typed_value(
        self,
        request_model: dict[str, Any],
        output: dict[str, Any],
    ) -> tuple[dict[str, Any], bytes]:
        prepared = prepare_rest_request("typed_value_retrieval", request_model)
        response = self._http.request(prepared.method, prepared.route)
        if response.status_code != 200:
            validate_error(response.json(), status=response.status_code)
            raise AssertionError("structured typed-value error validation returned")
        metadata = {
            "typed_value": {
                "node_id": output["node_id"],
                "output_port": output["output_port"],
                "port_type": output["port_type"],
                "port_content_digest": output["content_digest"],
                "value_manifest_reference": output["value_manifest_reference"],
                "value_index": request_model["value_index"],
                "value_count": output["value_count"],
                "value_content_digest": response.headers["Digest"],
                "size": len(response.content),
            }
        }
        validate_typed_value_response(metadata, response.headers, response.content)
        return metadata, response.content


def collect_run_events(
    websocket_origin: str,
    project_id: str,
    run_id: str,
) -> list[dict[str, object]]:
    stream = prepare_run_event_stream_request(
        {"project_id": project_id, "run_id": run_id}
    )
    messages: list[dict[str, object]] = []
    with connect(
        f"{websocket_origin}{stream.route}",
        open_timeout=5,
        close_timeout=5,
        proxy=None,
    ) as websocket:
        while True:
            message = json.loads(websocket.recv(timeout=30))
            validate_event(message)
            messages.append(message)
            if message["event"]["type"] == "run_terminal":
                return messages
