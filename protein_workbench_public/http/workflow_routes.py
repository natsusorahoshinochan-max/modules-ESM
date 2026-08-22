"""Current public Workflow Draft and Commit HTTP routes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request

from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from core.workflow.document import (
    WorkflowDocumentError,
    workflow_document_from_projection,
)
from protein_workbench_public.http.errors import (
    authoring_error_response,
    protocol_error_response,
    public_rest_wire_sources,
    workflow_document_error_response,
)
from protein_workbench_public.protocol import (
    REST_BODY_ABSENT,
    ProtocolValidationError,
    decode_rest_request,
    validate_response,
)


def register_workflow_routes(
    app: FastAPI,
    authoring: WorkflowAuthoringService,
    rest_operations: Mapping[str, Any],
) -> None:
    @app.get(
        rest_operations["project_workflow_draft"]["route"],
        include_in_schema=False,
    )
    async def public_project_workflow_draft(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "project_workflow_draft",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            payload = (
                authoring.load_draft(
                    admitted["project_id"]
                ).to_public()
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("project_workflow_draft", 200, payload)
        return payload

    @app.put(
        rest_operations["save_project_workflow_draft"]["route"],
        include_in_schema=False,
    )
    async def public_save_project_workflow_draft(
        request: Request,
        project_id: str,
    ) -> Any:
        workflow_payload: Any = None
        json_body: Any = REST_BODY_ABSENT
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "save_project_workflow_draft",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            workflow_payload = admitted["workflow"]
            workflow = workflow_document_from_projection(
                workflow_payload
            )
            snapshot = (
                authoring.save_draft(
                    admitted["project_id"],
                    workflow=workflow,
                ).to_public()
            )
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except ProtocolValidationError as error:
            return protocol_error_response(error, json_body)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("save_project_workflow_draft", 200, snapshot)
        return snapshot

    @app.get(
        rest_operations["project_active_workflow_commit"]["route"],
        include_in_schema=False,
    )
    async def public_project_active_workflow_commit(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "project_active_workflow_commit",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            receipt = (
                authoring.load_active_commit(
                    admitted["project_id"]
                ).to_public()
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("project_active_workflow_commit", 200, receipt)
        return receipt

    @app.post(
        rest_operations["commit_project_workflow"]["route"],
        include_in_schema=False,
    )
    async def public_commit_project_workflow(
        request: Request,
        project_id: str,
    ) -> Any:
        workflow_payload: Any = None
        json_body: Any = REST_BODY_ABSENT
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "commit_project_workflow",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            workflow_payload = admitted["workflow"]
            workflow = workflow_document_from_projection(
                workflow_payload
            )
            receipt = authoring.commit(
                admitted["project_id"],
                workflow=workflow,
            ).to_public()
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except ProtocolValidationError as error:
            return protocol_error_response(error, json_body)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        validate_response("commit_project_workflow", 200, receipt)
        return receipt
