"""Public WebSocket failure boundaries preserve normal disconnect semantics."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import WebSocket
from starlette.types import Message
from starlette.websockets import WebSocketState

from protein_workbench_public.http.emission import emit_run_event_stream_message
from protein_workbench_public.http.errors import websocket_internal_error_boundary


def _socket(*, disconnect_on_send: bool) -> tuple[WebSocket, list[Message]]:
    received = iter((
        {"type": "websocket.connect"},
        {"type": "websocket.disconnect", "code": 1000},
    ))
    sent: list[Message] = []

    async def receive() -> Message:
        return next(received)

    async def send(message: Message) -> None:
        sent.append(message)
        if disconnect_on_send and message["type"] == "websocket.send":
            # Starlette translates the transport's closed-socket OSError to
            # WebSocketDisconnect and marks its application state disconnected.
            raise OSError("client disconnected")

    return WebSocket({"type": "websocket"}, receive, send), sent


@pytest.mark.parametrize("disconnect_at", ["send", "receive"])
def test_client_disconnect_ends_stream_without_error_or_second_close(
    caplog: pytest.LogCaptureFixture, disconnect_at: str,
) -> None:
    websocket, sent = _socket(disconnect_on_send=disconnect_at == "send")

    @websocket_internal_error_boundary
    async def stream(socket: WebSocket) -> None:
        await socket.accept()
        if disconnect_at == "send":
            await emit_run_event_stream_message(socket, {"type": "run_event"})
        else:
            await socket.receive_text()

    asyncio.run(stream(websocket))

    assert [message["type"] for message in sent] == (
        ["websocket.accept", "websocket.send"]
        if disconnect_at == "send" else ["websocket.accept"]
    )
    assert caplog.records == []
    if disconnect_at == "send":
        assert websocket.application_state is WebSocketState.DISCONNECTED
    else:
        assert websocket.client_state is WebSocketState.DISCONNECTED


@pytest.mark.parametrize("disconnect_on_send", [False, True])
def test_internal_failure_is_reported_once_without_closing_a_disconnected_socket(
    caplog: pytest.LogCaptureFixture, disconnect_on_send: bool,
) -> None:
    websocket, sent = _socket(disconnect_on_send=disconnect_on_send)

    @websocket_internal_error_boundary
    async def stream(socket: WebSocket) -> None:
        await socket.accept()
        raise RuntimeError("private handler failure")

    asyncio.run(stream(websocket))

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
    assert "Unhandled public v2 WebSocket error" in record.getMessage()
    error_payload = json.loads(sent[1]["text"])
    assert error_payload["error"]["code"] == "internal_error"
    assert error_payload["error"]["message"] == "Internal server error"
    assert "private handler failure" not in sent[1]["text"]
    assert [message["type"] for message in sent] == (
        ["websocket.accept", "websocket.send"]
        if disconnect_on_send else ["websocket.accept", "websocket.send", "websocket.close"]
    )
    if not disconnect_on_send:
        assert sent[-1]["code"] == 1011
    assert websocket.application_state is WebSocketState.DISCONNECTED
