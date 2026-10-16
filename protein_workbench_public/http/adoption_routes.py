"""Explicit, durable adoption of published values into a target project."""
import json
import uuid
from collections.abc import Mapping
from typing import Any

from core.catalog.model import FrozenCatalog
from core.project.manager import ProjectManager, ProtectedProjectError
from core.project.adopted_input import AdoptedSnapshot
from core.execution.runtime import V2RunService

from fastapi import FastAPI, Request

from core.execution.ledger import V2RunError
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.errors import protocol_error_response, public_error_response, public_rest_wire_sources
from protein_workbench_public.protocol import ProtocolValidationError, decode_rest_request


def register_adoption_routes(
    app: FastAPI, catalog: FrozenCatalog, projects: ProjectManager,
    runtime: V2RunService, operations: Mapping[str, Any],
) -> None:
    @app.post(operations['adopt_result']['route'], include_in_schema=False)
    async def adopt(request: Request, project_id: str) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            value = decode_rest_request('adopt_result', path_parameters={'project_id': project_id},
                                        query_parameters=query, json_body=body)
            with runtime.project_mutation(project_id):
                try:
                    projects.require_meta(project_id)
                except FileNotFoundError:
                    return public_error_response('project_not_found', 'Project was not found',
                        {'resource_kind': 'project', 'resource_id': project_id})
                metadata, canonical, references = runtime.published_value(
                    value['source_project_id'], value['source_run_id'], value['node_id'],
                    value['output_port'], value['value_index'])
                typed = metadata['typed_value']
                type_id = typed['port_type']['contract_id']
                source = next((item for item in catalog.result_sources if item.port_type_id == type_id), None)
                if source is None:
                    raise ProtocolValidationError('$.output_port', 'No enabled module declares adoption for this value type')
                snapshot: AdoptedSnapshot = {
                    'port_type_id': type_id, 'canonical_value': canonical.decode('utf-8'),
                    'content_digest': typed['value_content_digest'],
                    'candidate_data': [{'candidate_id': ref.candidate_id, 'data_type_id': ref.data_type_id, 'content_digest': ref.content_digest} for ref in references],
                    'source': {'source_project_id': value['source_project_id'], 'source_run_id': value['source_run_id'], 'node_id': value['node_id'], 'output_port': value['output_port'], 'value_index': value['value_index']},
                }
                saved = projects.publish_input(project_id, 'input-' + uuid.uuid4().hex,
                    json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode('utf-8'),
                    filename='adopted-result.json')
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except ProtectedProjectError:
            return public_error_response('cross_scope_access_denied', 'Protected Project cannot be changed through this scope',
                {'requested_project_id': project_id})
        except V2RunError as error:
            return public_error_response(error.code, str(error), error.details)
        return emit_rest_json_success('adopt_result', {
            'project_input_ref': saved.project_input_ref,
            'source_node': {'node_type_id': source.node_type_id, 'binding_id': source.binding_id,
                            'node_parameters': {'project_input_ref': saved.project_input_ref}, 'binding_parameters': {}},
        })
