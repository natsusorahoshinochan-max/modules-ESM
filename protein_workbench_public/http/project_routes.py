"""Current public Project and Project Input HTTP routes."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any
import uuid

from fastapi import FastAPI, Request

from core.project.manager import (
    CANONICAL_3GB1_PROJECT_ID,
    WEBUI_3GB1_PROJECT_ID,
    ProjectInputDescriptor,
    ProjectManager,
    ProjectMeta,
    ProtectedProjectError,
)
from core.workflow.authoring import (
    WorkflowAuthoringError,
    WorkflowAuthoringService,
)
from protein_workbench_public.http.errors import (
    protocol_error_response,
    public_error_response,
    public_rest_wire_sources,
)
from protein_workbench_public.http.emission import emit_rest_json_success
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
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except WorkflowAuthoringError as error:
            from protein_workbench_public.http.errors import (
                authoring_error_response,
            )

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
            published = manager.publish_input(
                admitted["project_id"],
                f"input-{uuid.uuid4().hex}",
                content,
                filename=admitted["filename"],
            )
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
