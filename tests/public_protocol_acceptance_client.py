"""Bundle-driven acceptance client with no backend implementation imports."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx

from protein_workbench_public import (
    ProtocolValidationError,
    encode_project_input_content,
    prepare_rest_request,
)
from tests.support.protocol import (
    validate_artifact_response,
    validate_error,
    validate_event,
    validate_response,
    validate_typed_value_response,
)


class PublicProtocolAcceptanceClient:
    """Exercise only operations and payloads declared by the v2 bundle."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=transport,
            trust_env=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        operation_id: str,
        request_model: dict[str, Any],
    ) -> dict[str, Any]:
        prepared = prepare_rest_request(operation_id, request_model)
        response = self._http.request(
            prepared.method,
            prepared.route,
            json=prepared.json_body,
        )
        payload = response.json()
        validate_response(operation_id, response.status_code, payload)
        return payload

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
                "value_manifest_reference": output[
                    "value_manifest_reference"
                ],
                "value_index": request_model["value_index"],
                "value_count": output["value_count"],
                "value_content_digest": response.headers["Digest"],
                "size": len(response.content),
            }
        }
        validate_typed_value_response(metadata, response.headers, response.content)
        return metadata, response.content

    @staticmethod
    def validate_stream_message(payload: dict[str, Any]) -> None:
        try:
            validate_event(payload)
        except ProtocolValidationError as event_error:
            try:
                validate_error(payload)
            except ProtocolValidationError:
                raise event_error
