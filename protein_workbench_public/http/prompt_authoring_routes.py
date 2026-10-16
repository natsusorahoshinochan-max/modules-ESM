"""Current public Prompt Studio open and preview routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request

from core.workflow.authoring import WorkflowAuthoringError
from core.workflow.document import WorkflowDocumentError
from modules.prompt_authoring.authoring import PromptAuthoringService
from protein_workbench_public.authoring_codec import (
    encode_prompt_preview,
    encode_prompt_snapshot,
)
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.project_inputs import prospective_project_inputs
from protein_workbench_public.http.errors import (
    authoring_error_response,
    protocol_error_response,
    workflow_document_error_response,
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
            service = prompt_authoring.with_project_inputs(
                project_id, prospective_project_inputs(admitted.get("prospective_inputs", ())),
            )
            snapshot = service.open(admitted["project_id"], admitted)
        except ProtocolValidationError as error:
            return protocol_error_response(error, body)
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, body.get("workflow"))
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
            service = prompt_authoring.with_project_inputs(
                project_id, prospective_project_inputs(admitted.get("prospective_inputs", ())),
            )
            preview = service.preview(
                admitted["project_id"],
                admitted,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error, body)
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, body.get("workflow"))
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success(
            "preview_prompt_authoring",
            encode_prompt_preview(preview),
        )
