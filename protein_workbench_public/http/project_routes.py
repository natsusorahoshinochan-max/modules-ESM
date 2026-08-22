"""Current public Project and Project Input HTTP routes."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.project.manager import (
    PROJECT_SCHEMA_VERSION,
    ProjectManager,
    ProtectedProjectError,
)
from protein_workbench_public.http.errors import (
    protocol_error_response,
    public_error_response,
    public_rest_wire_sources,
)
from protein_workbench_public.protocol import (
    ProtocolValidationError,
    decode_rest_request,
)


def register_project_routes(
    app: FastAPI,
    projects: ProjectManager,
    rest_operations: Mapping[str, Any],
) -> None:
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
        payload = {
            "schema_namespace": "protein-workbench-public/v2",
            "id": meta.id,
            "name": meta.name,
            "created_at": meta.created_at,
            "modified_at": meta.modified_at,
            "seed": meta.seed,
        }
        status = create_project_operation["response"]["success_status"]
        return JSONResponse(status_code=status, content=payload)

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
        except ValueError:
            return public_error_response(
                "unsupported_schema_version",
                "Project metadata is not a supported exact v2 artifact",
                {
                    "artifact_kind": "project",
                    "expected_schema_version": PROJECT_SCHEMA_VERSION,
                    "received_schema_version": "unknown",
                },
            )
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
        payload = {
            "schema_namespace": "protein-workbench-public/v2",
            "project_id": admitted["project_id"],
            "project_input_ref": published.project_input_ref,
            "filename": published.filename,
            "size": published.size,
            "content_digest": published.content_digest,
        }
        status = publish_input_operation["response"]["success_status"]
        return JSONResponse(status_code=status, content=payload)

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
        except ValueError:
            return public_error_response(
                "unsupported_schema_version",
                "Project metadata is not a supported exact v2 artifact",
                {
                    "artifact_kind": "project",
                    "expected_schema_version": PROJECT_SCHEMA_VERSION,
                    "received_schema_version": "unknown",
                },
            )
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
        payload = {
            "schema_namespace": "protein-workbench-public/v2",
            "project_id": admitted["project_id"],
            "project_input_ref": descriptor.project_input_ref,
            "filename": descriptor.filename,
            "size": descriptor.size,
            "content_digest": descriptor.content_digest,
        }
        status = input_metadata_operation["response"]["success_status"]
        return JSONResponse(status_code=status, content=payload)
