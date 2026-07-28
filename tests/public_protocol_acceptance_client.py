"""Bundle-driven acceptance client with no backend implementation imports."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx

from protein_workbench_public import (
    ProtocolValidationError,
    prepare_rest_request,
    validate_artifact_response,
    validate_error,
    validate_event,
    validate_response,
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

    @staticmethod
    def validate_stream_message(payload: dict[str, Any]) -> None:
        try:
            validate_event(payload)
        except ProtocolValidationError as event_error:
            try:
                validate_error(payload)
            except ProtocolValidationError:
                raise event_error
