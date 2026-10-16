"""Dispatch module-owned read-only authoring actions through one public seam."""
from __future__ import annotations

import asyncio
from typing import Any
from fastapi import FastAPI, Request

from core.catalog.authoring_actions import AuthoringActionContext
from core.catalog.model import FrozenCatalog
from core.project.manager import ProjectInputDescriptor, ProjectManager
from core.workflow.authoring import WorkflowAuthoringError, WorkflowAuthoringService
from core.workflow.document import WorkflowDocumentError
from protein_workbench_public.protocol import ProtocolValidationError, decode_rest_request
from .emission import emit_rest_json_success
from .errors import (authoring_error_response, protocol_error_response,
                     public_error_response, public_rest_wire_sources,
                     workflow_document_error_response)
from .project_inputs import prospective_project_inputs


def register_authoring_action_routes(
    app: FastAPI, projects: ProjectManager,
    authoring: WorkflowAuthoringService, catalog: FrozenCatalog,
) -> None:
    @app.post('/api/v2/projects/{project_id}/authoring-actions/{action_id}', include_in_schema=False)
    async def invoke(request: Request, project_id: str, action_id: str) -> Any:
        parameters: dict[str, Any] = {}
        try:
            query, body = await public_rest_wire_sources(request)
            admitted = decode_rest_request('authoring_action',
                path_parameters={'project_id': project_id, 'action_id': action_id},
                query_parameters=query, json_body=body)
            action = next((item for item in catalog.authoring_actions if item.action_id == action_id), None)
            if action is None:
                return public_error_response('authoring_action_not_found', 'Authoring action is not enabled', {'action_id': action_id})
            try:
                projects.require_meta(project_id)
            except FileNotFoundError:
                return public_error_response('project_not_found', 'Project was not found',
                    {'resource_kind': 'project', 'resource_id': project_id})
            inputs = prospective_project_inputs(admitted.get('prospective_inputs', ()))

            def read_input(reference: str) -> tuple[ProjectInputDescriptor, bytes]:
                if reference in inputs:
                    return inputs[reference]
                try:
                    return projects.read_input(project_id, reference)
                except FileNotFoundError as error:
                    raise WorkflowAuthoringError('project_input_not_found', 'Project Input was not found',
                        details={'resource_kind': 'project_input', 'resource_id': reference}) from error

            context = AuthoringActionContext(project_id, projects, authoring, catalog, read_input)
            parameters = admitted['parameters']
            result = await asyncio.to_thread(action.apply, context, parameters)
            return emit_rest_json_success('authoring_action', result)
        except ProtocolValidationError as error:
            return protocol_error_response(error, parameters)
        except WorkflowDocumentError as error:
            return workflow_document_error_response(error, parameters.get('workflow'))
        except WorkflowAuthoringError as error:
            return authoring_error_response(error)
