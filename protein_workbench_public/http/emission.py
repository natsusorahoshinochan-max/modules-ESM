"""Single public REST JSON and WebSocket emission seams."""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket
from fastapi.responses import JSONResponse

from protein_workbench_public.protocol import (
    admit_rest_success_payload,
    admit_run_event_stream_message,
)


def emit_rest_json_success(
    operation_id: str,
    payload: Any,
) -> JSONResponse:
    """Validate and serialize one declared REST JSON success payload."""
    status, admitted = admit_rest_success_payload(operation_id, payload)
    return JSONResponse(status_code=status, content=admitted)


async def emit_run_event_stream_message(
    websocket: WebSocket,
    payload: Any,
) -> None:
    """Validate and send one complete Run Event Stream frame."""
    admitted = admit_run_event_stream_message(payload)
    await websocket.send_json(admitted)
