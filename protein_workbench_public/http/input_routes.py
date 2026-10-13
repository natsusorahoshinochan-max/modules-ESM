"""Read-only Project Input inspection at the scientific I/O owner."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request

from core.project.manager import ProjectManager
from modules.protein_io.errors import ProteinInputError
from modules.protein_io.inspection import inspect_project_input
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.errors import (
    protocol_error_response,
    public_error_response,
    public_rest_wire_sources,
)
from protein_workbench_public.protocol import ProtocolValidationError, decode_rest_request


def register_input_routes(
    app: FastAPI,
    projects: ProjectManager,
    operations: Mapping[str, Any],
) -> None:
    @app.post(operations["inspect_project_input"]["route"], include_in_schema=False)
    async def public_inspect_project_input(
        request: Request,
        project_id: str,
        project_input_ref: str,
    ) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request(
                "inspect_project_input",
                path_parameters={
                    "project_id": project_id,
                    "project_input_ref": project_input_ref,
                },
                query_parameters=query,
                json_body=body,
            )
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        try:
            projects.require_meta(project_id)
        except FileNotFoundError:
            return public_error_response(
                "project_not_found", "Project was not found",
                {"resource_kind": "project", "resource_id": project_id},
            )
        try:
            descriptor, payload = projects.read_input(project_id, project_input_ref)
        except FileNotFoundError:
            return public_error_response(
                "project_input_not_found", "Project Input was not found",
                {"resource_kind": "project_input", "resource_id": project_input_ref},
            )
        try:
            inspection = await asyncio.to_thread(
                inspect_project_input, payload, admitted["format"],
            )
        except ProteinInputError as error:
            return public_error_response(
                "project_input_invalid", str(error),
                {"project_input_ref": project_input_ref, "format": admitted["format"]},
            )
        return emit_rest_json_success("inspect_project_input", {
            "project_id": project_id,
            "project_input_ref": project_input_ref,
            "content_digest": descriptor.content_digest,
            **inspection,
        })
