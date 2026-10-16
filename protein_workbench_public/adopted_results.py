"""Read the existing producer settings needed to interpret an adopted value."""
from typing import Any

from core.catalog.model import FrozenCatalog
from core.execution.runtime import V2RunService
from core.project.manager import ProjectManager
from core.project.adopted_input import AdoptedSource, read_adopted_snapshot
from core.workflow.authoring import WorkflowAuthoringService
from datatypes.i_json import thaw_i_json


def original_parameters(
    source: AdoptedSource, *, runtime: V2RunService,
    authoring: WorkflowAuthoringService, projects: ProjectManager, catalog: FrozenCatalog,
) -> dict[str, Any]:
    project_id = source['source_project_id']
    run = runtime.projection(project_id, source['source_run_id'])
    commit = authoring.load_commit(project_id, workflow_commit_id=run.workflow_commit_id)
    node = next(node for node in commit.workflow.nodes if node.node_id == source['node_id'])
    if any(declaration.node_type_id == node.node_type_id for declaration in catalog.result_sources):
        _, payload = projects.read_input(project_id, node.node_parameters['project_input_ref'])
        return read_adopted_snapshot(payload)['parameters']
    publication = next(item for item in run.publications if item.node_id == source['node_id'])
    output = next(item for item in publication.outputs if item.output_port == source['output_port'])
    producer = runtime.projection(project_id, output.producer_run_id)
    producer_commit = authoring.load_commit(project_id, workflow_commit_id=producer.workflow_commit_id)
    matches = [original.node_id for original in producer.publications
        if original.result_identity == publication.result_identity
        for value in original.outputs
        if value.output_port == output.output_port
        and value.content_digest == output.content_digest
        and value.value_manifest_reference == output.value_manifest_reference
        and value.materialization['resolution'] == 'executed'
        and (output.materialization['resolution'] != 'executed' or original.node_id == source['node_id'])]
    recorded = producer_commit.workflow.canonical_projection()['nodes']
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
        })
    return {'status': 'recorded' if len(records) == 1 else 'ambiguous' if records else 'unavailable',
            'records': records}
