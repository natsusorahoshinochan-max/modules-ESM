"""Current public HTTP request parsing and error translation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
import json
import logging
import math
import re
from typing import Any
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from core.project.storage import StoragePathError
from core.workflow.authoring import (
    WorkflowAuthoringError,
)
from core.workflow.document import WorkflowDocumentError
from protein_workbench_public.protocol import (
    REST_BODY_ABSENT,
    ProtocolValidationError,
    load_bundle,
)


_LOGGER = logging.getLogger(__name__)


def public_error_payload(
    code: str,
    message: str,
    details: Mapping[str, Any],
) -> tuple[int, dict[str, Any]]:
    definition = load_bundle()["structured_errors"]["vocabulary"][code]
    payload = {
        "schema_namespace": "protein-workbench-public/v2",
        "error": {
            "code": code,
            "message": message,
            "retryable": definition["retryable"],
            "correlation_id": f"error-{uuid.uuid4().hex}",
            "details": dict(details),
        },
    }
    status = definition["http_status"]
    return status, payload


def public_error_response(
    code: str,
    message: str,
    details: Mapping[str, Any],
) -> JSONResponse:
    status, payload = public_error_payload(code, message, details)
    return JSONResponse(status_code=status, content=payload)


def report_public_internal_error(
    error: Exception,
    *,
    transport: str,
) -> str:
    incident_id = f"incident-{uuid.uuid4().hex}"
    _LOGGER.error(
        "Unhandled public v2 %s error incident_id=%s exception_type=%s",
        transport,
        incident_id,
        type(error).__name__,
        exc_info=True,
    )
    return incident_id


def protocol_error_field_path(
    error: ProtocolValidationError,
) -> list[str | int]:
    field_path: list[str | int] = []
    for match in re.finditer(r"\.([^.[\]]+)|\[([0-9]+)\]", error.path):
        name, index = match.groups()
        field_path.append(name if name is not None else int(index))
    return field_path


def protocol_error_response(
    error: ProtocolValidationError,
    json_body: Any = None,
) -> JSONResponse:
    if error.path == "$.workflow.schema_version":
        workflow_payload = (
            json_body.get("workflow")
            if isinstance(json_body, Mapping)
            else None
        )
        received = (
            workflow_payload.get("schema_version", "missing")
            if isinstance(workflow_payload, Mapping)
            else "invalid"
        )
        return public_error_response(
            "unsupported_schema_version",
            "Workflow schema version is unsupported",
            {
                "artifact_kind": "workflow",
                "expected_schema_version": "2.1.0",
                "received_schema_version": str(received)[:64] or "missing",
            },
        )
    return public_error_response(
        "malformed_request",
        str(error),
        {"field_path": protocol_error_field_path(error)},
    )


def _reject_duplicate_request_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _parse_finite_request_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-I-JSON numeric value {value!r}")
    return parsed


async def public_rest_wire_sources(
    request: Request,
) -> tuple[dict[str, str], Any]:
    query_parameters: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if name in query_parameters:
            raise ProtocolValidationError(
                f"$.{name}",
                "query parameter must appear exactly once",
            )
        query_parameters[name] = value

    raw_body = await request.body()
    if raw_body == b"":
        return query_parameters, REST_BODY_ABSENT
    try:
        json_body = json.loads(
            raw_body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_request_keys,
            parse_float=_parse_finite_request_float,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-I-JSON numeric value {value!r}")
            ),
        )
    except (UnicodeError, ValueError) as error:
        raise ProtocolValidationError(
            "$",
            "request body must be valid I-JSON",
        ) from error
    return query_parameters, json_body


def workflow_document_error_response(
    error: WorkflowDocumentError,
    payload: Any,
) -> JSONResponse:
    if error.code == "unsupported_schema_version":
        received = (
            payload.get("schema_version", "missing")
            if isinstance(payload, Mapping)
            else "invalid"
        )
        details: Mapping[str, Any] = {
            "artifact_kind": "workflow",
            "expected_schema_version": "2.1.0",
            "received_schema_version": str(received)[:64] or "missing",
        }
    elif error.code == "contract_digest_mismatch":
        details = {
            "issues": [
                {
                    "code": error.code,
                    "severity": "error",
                    "message": str(error),
                    "field_path": ["contract_lock"],
                }
            ]
        }
    else:
        details = {"field_path": ["workflow"]}
    return public_error_response(error.code, str(error), details)


def authoring_error_response(
    error: WorkflowAuthoringError,
) -> JSONResponse:
    return public_error_response(
        error.code,
        str(error),
        error.details,
    )


def websocket_internal_error_boundary(
    handler: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Translate an unknown WebSocket failure to the public protocol."""

    @wraps(handler)
    async def guarded(
        websocket: WebSocket,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        try:
            await handler(websocket, *args, **kwargs)
        except Exception as error:
            incident_id = report_public_internal_error(
                error,
                transport="WebSocket",
            )
            _, payload = public_error_payload(
                "internal_error",
                "Internal server error",
                {"incident_id": incident_id},
            )
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                pass
            await websocket.close(code=1011)

    return guarded


def install_error_handlers(app: FastAPI) -> None:
    """Install the current public framework and failure boundaries."""

    @app.exception_handler(StoragePathError)
    async def storage_path_error_handler(
        _request: Request,
        error: StoragePathError,
    ) -> JSONResponse:
        incident_id = report_public_internal_error(
            error,
            transport="REST",
        )
        return public_error_response(
            "internal_error",
            "Internal server error",
            {"incident_id": incident_id},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        body_error = any(
            item.get("loc", (None,))[0] == "body"
            for item in error.errors()
        )
        return public_error_response(
            "malformed_request",
            (
                "Request body is invalid"
                if body_error
                else "Request is invalid"
            ),
            {"field_path": []},
        )

    @app.middleware("http")
    async def public_internal_error_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            return await call_next(request)
        except Exception as error:
            incident_id = report_public_internal_error(
                error,
                transport="REST",
            )
            return public_error_response(
                "internal_error",
                "Internal server error",
                {"incident_id": incident_id},
            )
