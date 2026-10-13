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
    WORKFLOW_SCHEMA_VERSION,
    WorkflowDocumentError,
    workflow_document_from_canonical,
)
from protein_workbench_public.http.errors import (
    authoring_error_response,
    protocol_error_response,
    public_rest_wire_sources,
    workflow_document_error_response,
)
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.protocol import (
    REST_BODY_ABSENT,
    ProtocolValidationError,
    decode_rest_request,
)
from protein_workbench_public.workflow_codec import (
    encode_project_workspace,
    encode_workflow_version,
    encode_workflow_commit_receipt,
    encode_workflow_commit_snapshot,
    encode_workflow_draft,
)


def register_workflow_routes(
    app: FastAPI,
    authoring: WorkflowAuthoringService,
    rest_operations: Mapping[str, Any],
) -> None:
    @app.post(rest_operations["workflow_observation_options"]["route"], include_in_schema=False)
    async def public_observation_options(request: Request, project_id: str) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "workflow_observation_options", path_parameters={"project_id": project_id},
                query_parameters=query, json_body=body,
            )
            workflow = workflow_document_from_canonical({
                "schema_version": WORKFLOW_SCHEMA_VERSION,
                "workflow_id": project_id,
                **admitted["workflow"],
            })
            options = authoring.observation_options(project_id, workflow, ranking=admitted["ranking"])
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, body.get("workflow"))
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success("workflow_observation_options", {"options": options})

    @app.get(rest_operations["workflow_commit_snapshot"]["route"], include_in_schema=False)
    async def public_workflow_commit_snapshot(
        request: Request, project_id: str, workflow_commit_id: str,
    ) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "workflow_commit_snapshot",
                path_parameters={"project_id": project_id, "workflow_commit_id": workflow_commit_id},
                query_parameters=query, json_body=body,
            )
            payload = encode_workflow_commit_snapshot(authoring.load_commit(**admitted))
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success("workflow_commit_snapshot", payload)

    @app.post(rest_operations["compare_workflow_commit_science"]["route"], include_in_schema=False)
    async def public_compare_workflow_commit_science(
        request: Request, project_id: str, workflow_commit_id: str,
    ) -> Any:
        workflow_payload: Any = None
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "compare_workflow_commit_science",
                path_parameters={"project_id": project_id, "workflow_commit_id": workflow_commit_id},
                query_parameters=query, json_body=body,
            )
            workflow_payload = admitted["workflow"]
            workflow = workflow_document_from_canonical(workflow_payload)
            payload = authoring.compare_commit_science(
                project_id, workflow_commit_id=workflow_commit_id,
                workflow_project_id=admitted["workflow_project_id"], workflow=workflow,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success("compare_workflow_commit_science", payload)

    async def workspace_action(
        request: Request, project_id: str, operation: str,
        version_id: str | None = None,
    ) -> Any:
        workflow_payload: Any = None
        body: Any = REST_BODY_ABSENT
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                operation,
                path_parameters={
                    "project_id": project_id,
                    **({"version_id": version_id} if version_id is not None else {}),
                },
                query_parameters=query, json_body=body,
            )
            if operation == "project_workspace":
                payload = encode_project_workspace(authoring.load_workspace(project_id))
            elif operation == "save_project_workspace":
                workflow_payload = admitted.get("workflow")
                workflow = (
                    workflow_document_from_canonical(workflow_payload)
                    if workflow_payload is not None else None
                )
                payload = encode_project_workspace(authoring.save_workspace(
                    project_id, workflow=workflow, ui_state=admitted.get("ui_state"),
                    expected_draft_revision=admitted.get("expected_draft_revision"),
                ))
            elif operation == "list_workflow_versions":
                payload = {
                    "project_id": project_id,
                    "versions": [encode_workflow_version(v) for v in authoring.list_versions(project_id)],
                }
            elif operation == "name_workflow_version":
                payload = encode_workflow_version(authoring.name_version(
                    project_id, name=admitted["name"],
                ))
            elif operation == "workflow_version":
                version = authoring.load_version(project_id, admitted["version_id"])
                payload = {
                    "version": encode_workflow_version(version),
                    "workspace": encode_project_workspace(authoring.load_workspace(
                        project_id, revision=version.workspace_revision,
                    )),
                    "return_workspace_revision": authoring.load_workspace(project_id).workspace_revision,
                }
            elif operation == "fork_workflow_version":
                workflow_payload = admitted["workflow"]
                workflow = workflow_document_from_canonical(workflow_payload)
                payload = encode_project_workspace(authoring.fork_version(
                    project_id, version_id=admitted["version_id"],
                    return_workspace_revision=admitted["return_workspace_revision"],
                    workflow=workflow, ui_state=admitted["ui_state"],
                ))
            else:
                payload = encode_project_workspace(authoring.return_workspace(
                    project_id, workspace_revision=admitted["workspace_revision"],
                ))
        except ProtocolValidationError as error:
            return protocol_error_response(error, body)
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success(operation, payload)

    @app.get(rest_operations["project_workspace"]["route"], include_in_schema=False)
    async def public_project_workspace(request: Request, project_id: str) -> Any:
        return await workspace_action(request, project_id, "project_workspace")

    @app.put(rest_operations["save_project_workspace"]["route"], include_in_schema=False)
    async def public_save_project_workspace(request: Request, project_id: str) -> Any:
        return await workspace_action(request, project_id, "save_project_workspace")

    @app.get(rest_operations["list_workflow_versions"]["route"], include_in_schema=False)
    async def public_list_workflow_versions(request: Request, project_id: str) -> Any:
        return await workspace_action(request, project_id, "list_workflow_versions")

    @app.post(rest_operations["name_workflow_version"]["route"], include_in_schema=False)
    async def public_name_workflow_version(request: Request, project_id: str) -> Any:
        return await workspace_action(request, project_id, "name_workflow_version")

    @app.get(rest_operations["workflow_version"]["route"], include_in_schema=False)
    async def public_workflow_version(request: Request, project_id: str, version_id: str) -> Any:
        return await workspace_action(request, project_id, "workflow_version", version_id)

    @app.post(rest_operations["fork_workflow_version"]["route"], include_in_schema=False)
    async def public_fork_workflow_version(request: Request, project_id: str, version_id: str) -> Any:
        return await workspace_action(request, project_id, "fork_workflow_version", version_id)

    @app.post(rest_operations["return_project_workspace"]["route"], include_in_schema=False)
    async def public_return_project_workspace(request: Request, project_id: str) -> Any:
        return await workspace_action(request, project_id, "return_project_workspace")

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
            payload = encode_workflow_draft(
                authoring.load_draft(admitted["project_id"])
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success("project_workflow_draft", payload)

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
            receipt = encode_workflow_commit_receipt(
                authoring.load_active_commit(
                    admitted["project_id"]
                )
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success(
            "project_active_workflow_commit",
            receipt,
        )

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
            workflow = workflow_document_from_canonical(workflow_payload)
            receipt = encode_workflow_commit_receipt(
                authoring.commit(
                    admitted["project_id"],
                    workflow=workflow,
                )
            )
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, workflow_payload)
        except ProtocolValidationError as error:
            return protocol_error_response(error, json_body)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success("commit_project_workflow", receipt)
