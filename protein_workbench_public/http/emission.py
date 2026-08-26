"""Single public REST JSON and WebSocket emission seams."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import WebSocket
from fastapi.responses import JSONResponse

from protein_workbench_public.protocol import rest_success_status


def emit_rest_json_success(
    operation_id: str,
    payload: Mapping[str, Any],
) -> JSONResponse:
    """Serialize one response produced by a public wire projection."""
    return JSONResponse(
        status_code=rest_success_status(operation_id),
        content=payload,
    )


async def emit_run_event_stream_message(
    websocket: WebSocket,
    payload: Mapping[str, Any],
) -> None:
    """Send one frame produced by a public wire projection."""
    await websocket.send_json(payload)
