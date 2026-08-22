"""Current public Run REST and WebSocket routes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from core.execution.ledger import V2RunError
from core.execution.runtime import V2RunService
from core.workflow.authoring import WorkflowAuthoringError
from protein_workbench_public.ledger_codec import (
    decode_run_cursor,
    encode_cancellation_receipt,
    encode_event,
    encode_run_projection,
    public_timestamp,
)
from protein_workbench_public.http.errors import (
    authoring_error_response,
    protocol_error_field_path,
    protocol_error_response,
    public_error_payload,
    public_error_response,
    public_rest_wire_sources,
    websocket_internal_error_boundary,
)
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    artifact_content_disposition,
    decode_rest_request,
    decode_run_event_stream_request,
)


def register_run_routes(
    app: FastAPI,
    runtime: V2RunService,
    rest_operations: Mapping[str, Any],
    run_event_stream: Mapping[str, Any],
) -> None:
    @app.post(
        rest_operations["start_run"]["route"],
        include_in_schema=False,
    )
    async def public_start_run(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "start_run",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            receipt = runtime.start_background(
                admitted["project_id"],
                workflow_commit_id=admitted["workflow_commit_id"],
                client_request_id=admitted["client_request_id"],
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        return JSONResponse(status_code=202, content=receipt)

    @app.post(
        rest_operations["cancel_run"]["route"],
        include_in_schema=False,
    )
    async def public_cancel_run(
        request: Request,
        project_id: str,
        run_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "cancel_run",
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            decision = await asyncio.to_thread(
                runtime.cancel,
                admitted["project_id"],
                admitted["run_id"],
                after_cursor=decode_run_cursor(
                    admitted.get("after_sequence")
                ),
            )
            receipt = encode_cancellation_receipt(
                project_id=admitted["project_id"],
                run_id=admitted["run_id"],
                decision=decision,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        return receipt

    @app.post(
        rest_operations["start_derived_run"]["route"],
        include_in_schema=False,
    )
    async def public_start_derived_run(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "start_derived_run",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            receipt = (
                runtime.start_derived_background(
                    admitted["project_id"],
                    source_run_id=admitted["source_run_id"],
                    policy=admitted["policy"],
                    node_ids=admitted["node_ids"],
                    client_request_id=admitted["client_request_id"],
                )
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        return JSONResponse(status_code=202, content=receipt)

    @app.get(
        rest_operations["run_projection"]["route"],
        include_in_schema=False,
    )
    async def public_run_projection(
        request: Request,
        project_id: str,
        run_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "run_projection",
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            projection = encode_run_projection(
                runtime.projection(
                    admitted["project_id"],
                    admitted["run_id"],
                )
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        return projection

    @app.get(
        rest_operations["typed_value_retrieval"]["route"],
        include_in_schema=False,
    )
    async def public_v2_typed_value(
        request: Request,
        project_id: str,
        run_id: str,
        node_id: str,
        output_port: str,
        value_index: int,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "typed_value_retrieval",
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                    "node_id": node_id,
                    "output_port": output_port,
                    "value_index": value_index,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            metadata, body = runtime.typed_value(
                admitted["project_id"],
                admitted["run_id"],
                admitted["node_id"],
                admitted["output_port"],
                admitted["value_index"],
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        typed_value = metadata["typed_value"]
        headers = {
            "Content-Length": str(typed_value["size"]),
            "Content-Type": "application/json",
            "Digest": typed_value["value_content_digest"],
            "ETag": f'"{typed_value["value_content_digest"]}"',
            "X-Port-Content-Digest": typed_value[
                "port_content_digest"
            ],
            "X-Port-Type-Kind": typed_value["port_type"][
                "contract_kind"
            ],
            "X-Port-Type-Id": typed_value["port_type"]["contract_id"],
            "X-Port-Type-Version": typed_value["port_type"][
                "contract_version"
            ],
            "X-Port-Type-Digest": typed_value["port_type"][
                "contract_digest"
            ],
            "X-Value-Count": str(typed_value["value_count"]),
            "X-Value-Index": str(typed_value["value_index"]),
            "X-Value-Manifest-Reference": typed_value[
                "value_manifest_reference"
            ],
        }
        return Response(content=body, media_type=None, headers=headers)

    @app.get(
        rest_operations["artifact_retrieval"]["route"],
        include_in_schema=False,
    )
    async def public_v2_artifact(
        request: Request,
        project_id: str,
        run_id: str,
        artifact_reference: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "artifact_retrieval",
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                    "artifact_reference": artifact_reference,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            artifact, body = runtime.artifact(
                admitted["project_id"],
                admitted["run_id"],
                admitted["artifact_reference"],
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except V2RunError as error:
            return public_error_response(
                error.code,
                str(error),
                error.details,
            )
        content_disposition = artifact_content_disposition(
            artifact["filename"]
        )
        headers = {
            "Content-Disposition": content_disposition,
            "Content-Length": str(artifact["size"]),
            "Content-Type": artifact["media_type"],
            "Digest": artifact["content_digest"],
        }
        return Response(
            content=body,
            media_type=None,
            headers=headers,
        )

    @app.websocket(
        run_event_stream["route"].partition("?")[0]
    )
    @websocket_internal_error_boundary
    async def public_v2_run_events(
        websocket: WebSocket,
        project_id: str,
        run_id: str,
    ) -> None:
        await websocket.accept()
        after_sequence: str | None = None
        try:
            query_parameters: dict[str, str] = {}
            for name, value in websocket.query_params.multi_items():
                if name in query_parameters:
                    raise ProtocolValidationError(
                        f"$.{name}",
                        "query parameter must appear exactly once",
                    )
                query_parameters[name] = value
            after_sequence = query_parameters.get("after_sequence")
            admitted = decode_run_event_stream_request(
                path_parameters={
                    "project_id": project_id,
                    "run_id": run_id,
                },
                query_parameters=query_parameters,
            )
            project_id = admitted["project_id"]
            run_id = admitted["run_id"]
            after_sequence = admitted.get("after_sequence")
            replay = runtime.replay(
                project_id,
                run_id,
                decode_run_cursor(after_sequence),
            )
            replay_after_sequence = replay.after_sequence
            replay_after_cursor = replay.after_cursor.value
            replay_through_sequence = replay.through_sequence
            replay_through_cursor = replay.through_cursor.value
            terminal = replay.terminal
            replay_started = {
                "schema_namespace": "protein-workbench-public/v2",
                "project_id": project_id,
                "run_id": run_id,
                "sequence": replay_after_sequence,
                "cursor": replay_after_cursor,
                "emitted_at": public_timestamp(),
                "event": {
                    "type": "replay_started",
                    "replay_through_cursor": replay_through_cursor,
                    **(
                        {"after_sequence": after_sequence}
                        if after_sequence is not None
                        else {}
                    ),
                },
            }
            await websocket.send_json(replay_started)
            for fact in replay.events:
                event = encode_event(
                    project_id=project_id,
                    run_id=run_id,
                    fact=fact,
                )
                await websocket.send_json(event)
            replay_complete = {
                "schema_namespace": "protein-workbench-public/v2",
                "project_id": project_id,
                "run_id": run_id,
                "sequence": replay_through_sequence,
                "cursor": replay_through_cursor,
                "emitted_at": public_timestamp(),
                "event": {
                    "type": "replay_complete",
                    "live_from_cursor": replay_through_cursor,
                },
            }
            await websocket.send_json(replay_complete)
            live_after_sequence = replay_through_sequence
            while not terminal:
                live_events, observed_sequence, terminal = await asyncio.to_thread(
                    runtime.wait_for_events,
                    project_id,
                    run_id,
                    live_after_sequence,
                    timeout_seconds=1.0,
                )
                for fact in live_events:
                    event = encode_event(
                        project_id=project_id,
                        run_id=run_id,
                        fact=fact,
                    )
                    await websocket.send_json(event)
                live_after_sequence = observed_sequence
            await websocket.close(code=1000)
        except (ProtocolValidationError, V2RunError) as error:
            if isinstance(error, V2RunError):
                code = error.code
                message = str(error)
                details = error.details
            else:
                if (
                    error.path == "$.after_sequence"
                    and after_sequence is not None
                ):
                    code = "invalid_cursor"
                    message = "Run Event Stream cursor is invalid"
                    details = {
                        "after_sequence": (
                            after_sequence
                            if isinstance(after_sequence, str)
                            and 1 <= len(after_sequence) <= 512
                            else "invalid"
                        )
                    }
                else:
                    code = "malformed_request"
                    message = str(error)
                    details = {
                        "field_path": protocol_error_field_path(error)
                    }
            _, payload = public_error_payload(code, message, details)
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.send_json(payload)
            await websocket.close(code=1008)
