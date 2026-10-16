"""Explicit, durable adoption of published values into a target project."""
import json
import uuid
from collections.abc import Mapping
from typing import Any

from core.catalog.model import FrozenCatalog
from core.project.manager import ProjectManager, ProtectedProjectError
from core.project.adopted_input import AdoptedSnapshot, read_adopted_snapshot
from core.workflow.authoring import WorkflowAuthoringService
from protein_workbench_public.adopted_results import original_parameters, dependency_values
from core.execution.runtime import V2RunService
from datatypes.i_json import thaw_i_json

from fastapi import FastAPI, Request

from core.execution.ledger import V2RunError
from protein_workbench_public.http.emission import emit_rest_json_success
from protein_workbench_public.http.errors import protocol_error_response, public_error_response, public_rest_wire_sources
from protein_workbench_public.protocol import ProtocolValidationError, decode_rest_request


def register_adoption_routes(
    app: FastAPI, catalog: FrozenCatalog, projects: ProjectManager,
    runtime: V2RunService, authoring: WorkflowAuthoringService, operations: Mapping[str, Any],
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
                    'parameters': {}, 'dependencies': [], 'axis_digests': [], 'definitions': [],
                    'candidate_data': [{'candidate_id': ref.candidate_id, 'data_type_id': ref.data_type_id, 'content_digest': ref.content_digest} for ref in references],
                    'source': {'source_project_id': value['source_project_id'], 'source_run_id': value['source_run_id'], 'node_id': value['node_id'], 'output_port': value['output_port'], 'value_index': value['value_index']},
                }
                if source.observations is not None:
                    observations = source.observations(canonical)
                    required_definitions = {reference.key for observation in observations for reference in (observation.metric, observation.method)}
                    source_run = runtime.projection(value['source_project_id'], value['source_run_id'])
                    source_commit = authoring.recorded_commit(value['source_project_id'], workflow_commit_id=source_run.workflow_commit_id)
                    snapshot['definitions'] = [thaw_i_json(definition) for definition in source_commit.scientific_definitions
                        if (definition['contract_kind'], definition['contract_id']) in required_definitions]
                    if len(snapshot['definitions']) != len(required_definitions):
                        raise ValueError('Published observations lack their recorded Metric or Method definition')
                snapshot['parameters'] = original_parameters(snapshot['source'], runtime=runtime, authoring=authoring, projects=projects, catalog=catalog)
                if source.dependencies is not None:
                    dependencies = source.dependencies(canonical, dependency_values(snapshot['source'],
                        runtime=runtime, authoring=authoring, projects=projects, catalog=catalog))
                    for dependency in dependencies:
                        if not dependency['parameters']:
                            dependency['parameters'] = original_parameters(dependency['source'], runtime=runtime,
                                authoring=authoring, projects=projects, catalog=catalog)
                    snapshot['dependencies'] = list(dependencies)
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

    @app.get(operations['adopted_input_metadata']['route'], include_in_schema=False)
    async def metadata(request: Request, project_id: str, project_input_ref: str) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            decode_rest_request('adopted_input_metadata', path_parameters={
                'project_id': project_id, 'project_input_ref': project_input_ref},
                query_parameters=query, json_body=body)
            _, payload = projects.read_input(project_id, project_input_ref)
            snapshot = read_adopted_snapshot(payload)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        except FileNotFoundError:
            return public_error_response('project_input_not_found', 'Project Input was not found',
                {'resource_kind': 'project_input', 'resource_id': project_input_ref})
        return emit_rest_json_success('adopted_input_metadata', {
            'source': snapshot['source'], 'parameters': snapshot['parameters'], 'dependencies': snapshot['dependencies'], 'definitions': snapshot['definitions'],
        })

    @app.get(operations['result_sources']['route'], include_in_schema=False)
    async def sources(request: Request) -> Any:
        try:
            query, body = await public_rest_wire_sources(request)
            decode_rest_request('result_sources', query_parameters=query, json_body=body)
        except ProtocolValidationError as error:
            return protocol_error_response(error)
        return emit_rest_json_success('result_sources', {'sources': [{'port_type_id': source.port_type_id, 'node_type_id': source.node_type_id, 'binding_id': source.binding_id, 'output_port': source.output_port} for source in catalog.result_sources]})
