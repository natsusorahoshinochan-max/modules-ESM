"""Read the existing producer settings needed to interpret an adopted value."""
from typing import Any

from core.catalog.model import FrozenCatalog
from core.execution.runtime import V2RunService
from core.execution.ledger import V2RunError
from core.project.manager import ProjectManager
from core.project.adopted_input import AdoptedSource, AdoptedSnapshot, read_adopted_snapshot
from collections.abc import Iterator
from core.workflow.authoring import WorkflowAuthoringService, WorkflowAuthoringError
from datatypes.i_json import thaw_i_json


def _original_parameters(
    source: AdoptedSource, *, runtime: V2RunService,
    authoring: WorkflowAuthoringService, projects: ProjectManager, catalog: FrozenCatalog,
) -> dict[str, Any]:
    project_id = source['source_project_id']
    run = runtime.projection(project_id, source['source_run_id'])
    commit = authoring.recorded_commit(project_id, workflow_commit_id=run.workflow_commit_id)
    node = next(node for node in commit.workflow['nodes'] if node['node_id'] == source['node_id'])
    if any(definition['contract_kind'] == 'node_type' and definition['contract_id'] == node['node_type_id'] and definition['descriptor'].get('restored_output_port') == source['output_port'] for definition in commit.scientific_definitions):
        _, payload = projects.read_input(project_id, node['node_parameters']['project_input_ref'])
        return read_adopted_snapshot(payload)['parameters']
    publication = next(item for item in run.publications if item.node_id == source['node_id'])
    output = next(item for item in publication.outputs if item.output_port == source['output_port'])
    producer = runtime.projection(project_id, output.producer_run_id)
    producer_commit = authoring.recorded_commit(project_id, workflow_commit_id=producer.workflow_commit_id)
    matches = [original.node_id for original in producer.publications
        if original.result_identity == publication.result_identity
        for value in original.outputs
        if value.output_port == output.output_port
        and value.content_digest == output.content_digest
        and value.value_manifest_reference == output.value_manifest_reference
        and value.materialization['resolution'] == 'executed'
        and (output.materialization['resolution'] != 'executed' or original.node_id == source['node_id'])]
    recorded = thaw_i_json(producer_commit.workflow)['nodes']
    admitted = thaw_i_json(producer_commit.scientific_identity)['nodes']
    records = []
    for node_id in dict.fromkeys(matches):
        original_node = next((item for item in recorded if item['node_id'] == node_id), None)
        if original_node is None:
            continue
        original_admitted = next((item for item in admitted if item['node_id'] == node_id), None)
        records.append({
            **original_node, 'project_id': project_id, 'run_id': producer.run_id,
            'workflow_commit_id': producer.workflow_commit_id,
            'admitted_parameters': None if original_admitted is None else {
                'node_parameters': original_admitted['node_parameters'],
                'binding_parameters': original_admitted['binding_parameters'],
            },
            'definitions': [] if original_admitted is None else original_admitted['result_identity_plan_facts']['identity_facts']['resolved_result_contracts'],
        })
    return {'status': 'recorded' if len(records) == 1 else 'ambiguous' if records else 'unavailable',
            'records': records}


def original_parameters(
    source: AdoptedSource, *, runtime: V2RunService,
    authoring: WorkflowAuthoringService, projects: ProjectManager, catalog: FrozenCatalog,
) -> dict[str, Any]:
    try:
        return _original_parameters(source, runtime=runtime, authoring=authoring, projects=projects, catalog=catalog)
    except (V2RunError, WorkflowAuthoringError) as error:
        if error.code not in {'run_not_found', 'workflow_commit_not_found'}:
            raise
        return {'status': 'unavailable', 'records': []}


def dependency_values(source: AdoptedSource, *, runtime: V2RunService,
                      authoring: WorkflowAuthoringService, projects: ProjectManager,
                      catalog: FrozenCatalog) -> Iterator[AdoptedSnapshot]:
    """Expose published values to the module that owns dependency selection."""
    run = runtime.projection(source['source_project_id'], source['source_run_id'])
    commit = authoring.recorded_commit(source['source_project_id'], workflow_commit_id=run.workflow_commit_id)
    source_nodes = {definition['contract_id'] for definition in commit.scientific_definitions if definition['contract_kind'] == 'node_type' and definition['descriptor'].get('restored_output_port') is not None}
    for node in commit.workflow['nodes']:
        if node['node_type_id'] in source_nodes:
            _, payload = projects.read_input(source['source_project_id'], node['node_parameters']['project_input_ref'])
            snapshot = read_adopted_snapshot(payload)
            yield snapshot
            yield from snapshot['dependencies']
    for publication in run.publications:
        for output in publication.outputs:
            for value_index in range(output.value_count):
                location: AdoptedSource = {**source, 'node_id': publication.node_id,
                    'output_port': output.output_port, 'value_index': value_index}
                metadata, canonical, references = runtime.published_value(
                    source['source_project_id'], source['source_run_id'], publication.node_id, output.output_port, value_index)
                port = catalog.get_port_type(output.port_type.contract_id)
                axes = port.scientific_axis_references(port.restore(canonical)) if port is not None and port.runtime_scientific_axis_projection is not None else ()
                yield {'definitions': [], 'axis_digests': [axis.axis_content_digest for axis in axes],
                    'port_type_id': output.port_type.contract_id, 'canonical_value': canonical.decode('utf-8'),
                    'content_digest': metadata['typed_value']['value_content_digest'],
                    'candidate_data': [{'candidate_id': ref.candidate_id, 'data_type_id': ref.data_type_id,
                                        'content_digest': ref.content_digest} for ref in references],
                    'source': location, 'parameters': {}, 'dependencies': []}
