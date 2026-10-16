"""Current public Project and Project Input HTTP routes."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any
import uuid

from fastapi import FastAPI, Request

from core.execution.ledger import V2RunError
from core.execution.runtime import V2RunService
from core.project.manager import (
    CANONICAL_3GB1_PROJECT_ID,
    WEBUI_3GB1_PROJECT_ID,
    ProjectInputDescriptor,
    ProjectManager,
    ProjectMeta,
    ProjectStateError,
    ProtectedProjectError,
)
from core.workflow.document import workflow_document_from_canonical, WorkflowDocumentError
from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from protein_workbench_public.http.errors import (
    authoring_error_response,
    workflow_document_error_response,
    protocol_error_response,
    public_error_response,
    public_rest_wire_sources,
)
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.project_inputs import prospective_project_inputs
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    decode_rest_request,
)


def _project_metadata_payload(
    meta: ProjectMeta,
    projects: ProjectManager,
) -> dict[str, Any]:
    return {
        "schema_namespace": "protein-workbench-public/v2",
        "id": meta.id,
        "name": meta.name,
        "created_at": meta.created_at,
        "modified_at": meta.modified_at,
        "seed": meta.seed,
        "project_kind": (
            "default_example"
            if meta.id == WEBUI_3GB1_PROJECT_ID
            else "canonical_verification"
            if meta.id == CANONICAL_3GB1_PROJECT_ID
            else "personal"
        ),
        "copied_from_project_id": meta.copied_from_project_id,
        "reference_results_project_id": meta.reference_results_project_id,
        "deleted_at": meta.deleted_at,
        "latest_run_id": projects.latest_run_id(meta.id),
    }


def _project_input_payload(
    project_id: str,
    descriptor: ProjectInputDescriptor,
) -> dict[str, Any]:
    return {
        "schema_namespace": "protein-workbench-public/v2",
        "project_id": project_id,
        "project_input_ref": descriptor.project_input_ref,
        "filename": descriptor.filename,
        "size": descriptor.size,
        "content_digest": descriptor.content_digest,
    }


def register_project_routes(
    app: FastAPI,
    projects: ProjectManager,
    authoring: WorkflowAuthoringService,
    rest_operations: Mapping[str, Any],
    runtime: V2RunService,
) -> None:
    list_projects_operation = rest_operations["list_projects"]

    @app.get(
        list_projects_operation["route"].partition("?")[0],
        include_in_schema=False,
    )
    async def public_list_projects(request: Request) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "list_projects",
                query_parameters=query_parameters,
                json_body=json_body,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        payload = {
            "schema_namespace": "protein-workbench-public/v2",
            "projects": [
                _project_metadata_payload(meta, projects)
                for meta in projects.list_projects(name=admitted.get("name"))
            ],
        }
        return emit_rest_json_success("list_projects", payload)

    @app.get(rest_operations["list_deleted_projects"]["route"], include_in_schema=False)
    async def public_list_deleted_projects(request: Request) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            decode_rest_request(
                "list_deleted_projects", query_parameters=query, json_body=body,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        return emit_rest_json_success("list_deleted_projects", {
            "schema_namespace": "protein-workbench-public/v2",
            "projects": [
                _project_metadata_payload(meta, projects)
                for meta in projects.list_projects(deleted=True)
            ],
        })

    async def project_action(
        request: Request, project_id: str, operation: str,
    ) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                operation, path_parameters={"project_id": project_id},
                query_parameters=query, json_body=body,
            )
            if operation == "rename_project":
                with runtime.project_mutation(project_id):
                    meta = projects.rename(project_id, admitted["name"])
            elif operation == "duplicate_project":
                meta = authoring.duplicate_project(project_id, name=admitted["name"])
            elif operation == "restore_project":
                with runtime.project_mutation(project_id):
                    meta = projects.restore(project_id)
            elif operation == "trash_project":
                meta = runtime.trash_project(project_id)
            else:
                runtime.permanently_delete_project(project_id)
                return emit_rest_json_success(operation, {"project_id": project_id, "deleted": True})
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        except V2RunError as error:
            return public_error_response(error.code, str(error), error.details)
        except ProtectedProjectError:
            return public_error_response(
                "cross_scope_access_denied", "Protected example Projects are read-only",
                {"requested_project_id": project_id},
            )
        except ProjectStateError as error:
            return public_error_response(
                "project_state_conflict", str(error), {"project_id": project_id},
            )
        except FileNotFoundError:
            return public_error_response(
                "project_not_found", "Project was not found",
                {"resource_kind": "project", "resource_id": project_id},
            )
        return emit_rest_json_success(operation, _project_metadata_payload(meta, projects))

    @app.patch(rest_operations["rename_project"]["route"], include_in_schema=False)
    async def public_rename_project(request: Request, project_id: str) -> Any:
        return await project_action(request, project_id, "rename_project")

    @app.post(rest_operations["duplicate_project"]["route"], include_in_schema=False)
    async def public_duplicate_project(request: Request, project_id: str) -> Any:
        return await project_action(request, project_id, "duplicate_project")

    @app.post(rest_operations["trash_project"]["route"], include_in_schema=False)
    async def public_trash_project(request: Request, project_id: str) -> Any:
        return await project_action(request, project_id, "trash_project")

    @app.post(rest_operations["restore_project"]["route"], include_in_schema=False)
    async def public_restore_project(request: Request, project_id: str) -> Any:
        return await project_action(request, project_id, "restore_project")

    @app.delete(rest_operations["delete_project"]["route"], include_in_schema=False)
    async def public_delete_project(request: Request, project_id: str) -> Any:
        return await project_action(request, project_id, "delete_project")

    @app.get(rest_operations["list_project_inputs"]["route"], include_in_schema=False)
    async def public_list_project_inputs(request: Request, project_id: str) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            decode_rest_request(
                "list_project_inputs", path_parameters={"project_id": project_id},
                query_parameters=query, json_body=body,
            )
            projects.require_meta(project_id)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except FileNotFoundError:
            return public_error_response(
                "project_not_found", "Project was not found",
                {"resource_kind": "project", "resource_id": project_id},
            )
        return emit_rest_json_success("list_project_inputs", {
            "project_id": project_id,
            "inputs": [
                _project_input_payload(project_id, projects.read_input(project_id, ref)[0])
                for ref in projects.stored_input_references(project_id)
            ],
        })

    create_project_operation = rest_operations["create_project"]

    @app.post(create_project_operation["route"], include_in_schema=False)
    async def public_create_project(request: Request) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "create_project",
                query_parameters=query_parameters,
                json_body=json_body,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        meta = projects.create(admitted["name"])
        payload = _project_metadata_payload(meta, projects)
        return emit_rest_json_success("create_project", payload)

    copy_project_operation = rest_operations["copy_example_project"]

    @app.post(copy_project_operation["route"], include_in_schema=False)
    async def public_copy_example_project(
        request: Request,
        project_id: str,
    ) -> Any:
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "copy_example_project",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            meta = authoring.copy_project(
                admitted["project_id"],
                name=admitted["name"],
                workflow=(workflow_document_from_canonical(admitted["workflow"])
                          if "workflow" in admitted else None),
                ui_state=admitted.get("ui_state"),
                inputs=prospective_project_inputs(admitted.get("inputs", ())),
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, json_body.get("workflow"))
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
        return emit_rest_json_success(
            "copy_example_project",
            _project_metadata_payload(meta, projects),
        )

    publish_input_operation = rest_operations["publish_project_input"]

    @app.post(publish_input_operation["route"], include_in_schema=False)
    async def public_publish_project_input(
        request: Request,
        project_id: str,
    ) -> Any:
        manager = projects
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "publish_project_input",
                path_parameters={"project_id": project_id},
                query_parameters=query_parameters,
                json_body=json_body,
            )
            content = base64.b64decode(admitted["content_base64"])
            project = manager.load_meta(admitted["project_id"])
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        if project is None:
            return public_error_response(
                "project_not_found",
                "Project was not found",
                {
                    "resource_kind": "project",
                    "resource_id": admitted["project_id"],
                },
            )
        try:
            with runtime.project_mutation(project_id):
                published = manager.publish_input(
                    admitted["project_id"],
                    f"input-{uuid.uuid4().hex}",
                    content,
                    filename=admitted["filename"],
                )
        except V2RunError as error:
            return public_error_response(error.code, str(error), error.details)
        except ProtectedProjectError:
            return public_error_response(
                "cross_scope_access_denied",
                "Protected Project cannot be changed through this scope",
                {"requested_project_id": admitted["project_id"]},
            )
        payload = _project_input_payload(admitted["project_id"], published)
        return emit_rest_json_success("publish_project_input", payload)

    input_metadata_operation = rest_operations["project_input_metadata"]

    @app.get(input_metadata_operation["route"], include_in_schema=False)
    async def public_project_input_metadata(
        request: Request,
        project_id: str,
        project_input_ref: str,
    ) -> Any:
        manager = projects
        try:
            query_parameters, json_body = await public_rest_wire_sources(
                request
            )
            admitted = decode_rest_request(
                "project_input_metadata",
                path_parameters={
                    "project_id": project_id,
                    "project_input_ref": project_input_ref,
                },
                query_parameters=query_parameters,
                json_body=json_body,
            )
            project = manager.load_meta(admitted["project_id"])
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        if project is None:
            return public_error_response(
                "project_not_found",
                "Project was not found",
                {
                    "resource_kind": "project",
                    "resource_id": admitted["project_id"],
                },
            )
        try:
            descriptor, _ = manager.read_input(
                admitted["project_id"],
                admitted["project_input_ref"],
            )
        except FileNotFoundError:
            return public_error_response(
                "project_input_not_found",
                "Project Input was not found",
                {
                    "resource_kind": "project_input",
                    "resource_id": admitted["project_input_ref"],
                },
            )
        payload = _project_input_payload(admitted["project_id"], descriptor)
        return emit_rest_json_success("project_input_metadata", payload)
