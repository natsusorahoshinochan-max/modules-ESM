"""Current public Prompt Studio open, preview, and apply routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request

from core.workflow.authoring import WorkflowAuthoringError
from modules.prompt_authoring.authoring import PromptAuthoringService
from protein_workbench_public.authoring_codec import (
    encode_prompt_apply_result,
    encode_prompt_preview,
    encode_prompt_snapshot,
)
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.errors import (
    authoring_error_response,
    protocol_error_response,
    public_rest_wire_sources,
)
from protein_workbench_public.protocol import (
    REST_BODY_ABSENT,
    ProtocolValidationError,
    decode_rest_request,
)


def register_prompt_authoring_routes(
    app: FastAPI,
    prompt_authoring: PromptAuthoringService,
    rest_operations: Mapping[str, Any],
) -> None:
    @app.post(
        rest_operations["open_prompt_authoring"]["route"],
        include_in_schema=False,
    )
    async def public_open_prompt_authoring(
        request: Request,
        project_id: str,
    ) -> Any:
        body: Any = REST_BODY_ABSENT
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "open_prompt_authoring",
                path_parameters={"project_id": project_id},
                query_parameters=query,
                json_body=body,
            )
            snapshot = prompt_authoring.open(admitted["project_id"], admitted)
        except ProtocolValidationError as error:
            return protocol_error_response(error, body)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success(
            "open_prompt_authoring",
            encode_prompt_snapshot(snapshot),
        )

    @app.post(
        rest_operations["preview_prompt_authoring"]["route"],
        include_in_schema=False,
    )
    async def public_preview_prompt_authoring(
        request: Request,
        project_id: str,
    ) -> Any:
        body: Any = REST_BODY_ABSENT
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "preview_prompt_authoring",
                path_parameters={"project_id": project_id},
                query_parameters=query,
                json_body=body,
            )
            preview = prompt_authoring.preview(
                admitted["project_id"],
                admitted["document"],
                composition_id=admitted.get("composition_id"),
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error, body)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success(
            "preview_prompt_authoring",
            encode_prompt_preview(preview),
        )

    @app.post(
        rest_operations["apply_prompt_authoring"]["route"],
        include_in_schema=False,
    )
    async def public_apply_prompt_authoring(
        request: Request,
        project_id: str,
    ) -> Any:
        body: Any = REST_BODY_ABSENT
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "apply_prompt_authoring",
                path_parameters={"project_id": project_id},
                query_parameters=query,
                json_body=body,
            )
            result = prompt_authoring.apply(
                admitted["project_id"],
                intent=admitted["intent"],
                normalized_document=admitted["normalized_document"],
                preview_digest=admitted["preview_digest"],
                composition_id=admitted.get("composition_id"),
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error, body)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success(
            "apply_prompt_authoring",
            encode_prompt_apply_result(result),
        )
