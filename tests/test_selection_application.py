"""Public application scenario for node-owned raw Selection (spec #126)."""
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import time
import json

from fastapi.testclient import TestClient
from core.catalog.authoring import build_authoring_capability_projection
from core.catalog.builder import build_frozen_catalog
from core.catalog.declarations import (AvailabilityDeclaration, AvailabilityResult,
    ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration, ScientificOperationFactory)
from core.catalog.definition_resource import DefinitionResource
from core.catalog.observation import ProducedObservation
from core.catalog.port_contract import BehaviorReference
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.execution.runtime import V2RunService
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from datatypes.candidate import Candidate, CandidateCollection
from datatypes.exact_reference import ExactContractReference as Ref
from datatypes.observation import IntrinsicContextProfile, IntrinsicObservationContext, ScoreCollection, ScoreObservation
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from modules.collection_ops.package import MODULE_PACKAGE as COLLECTIONS
from modules.selection.package import MODULE_PACKAGE
from protein_workbench_public.http.app import create_http_app


class StudyData:
    def __init__(self, operation):
        self.operation = operation

    def execute(self, call):
        if self.operation == 'sequence_values':
            return {'sequences': tuple(ProteinSequence(value) for value in call.node_parameters['values'])}
        if self.operation == 'slot_pick':
            if isinstance(call.node_parameters['selected_slot'], Mapping):
                return {'sequence': ProteinSequence('W')}
            values = call.inputs['sequences'].slots[call.node_parameters['selected_slot']]
            return {'sequence': ProteinSequence(''.join(item.value.sequence for item in values))}
        if self.operation == 'backbone':
            index = call.node_parameters['index']
            structure = ProteinStructure('ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 50.00           C  \nEND\n')
            return {'candidates': CandidateCollection('backbone', 'protein.structure', (Candidate(f'backbone-{index}', structure),))}
        if self.operation == 'candidates':
            population = [('zeta', 'AA'), ('alpha', 'AC'), ('last', 'AD')]
            population.extend((f'candidate-{index:03d}', 'A' * (index + 1)) for index in range(3, 250))
            return {'candidates': CandidateCollection('study', 'protein.sequence', tuple(
                Candidate(name, ProteinSequence(sequence), metadata={'display_name': name})
                for name, sequence in population
            [call.node_parameters['start']:call.node_parameters['start'] + call.node_parameters['count']]))}
        return {'scores': ScoreCollection('measurements', tuple(ScoreObservation(
            subject=reference, metric=Ref('metric', 'selection_fixture.raw'),
            method=Ref('method', 'selection_fixture.scores.method'), context=IntrinsicObservationContext(),
            source_partition='raw', value=value,
        ) for reference, value in zip(call.inputs['candidates'].candidate_data, call.node_parameters['values'])
            if value is not None))}


def study_registration():
    methods = tuple(MethodDefinition(f'selection_fixture.{name}.method', {'name': name}, {}, {}, {})
                    for name in ('candidates', 'scores', 'sequence_values', 'slot_pick', 'backbone'))
    bindings = tuple(ExecutionBindingDefinition(
        binding_id=f'selection_fixture.{name}.direct', node_type=Ref('node_type', f'selection_fixture.{name}'),
        method=Ref('method', f'selection_fixture.{name}.method'), binding_parameters={}, execution_route='direct',
        factory=ScientificOperationFactory(BehaviorReference(f'fixture/{name}'), lambda context, op=name: StudyData(op)),
        availability=AvailabilityDeclaration(BehaviorReference(f'fixture/{name}/available'), {}, AvailabilityResult.available),
        deterministic=True, cacheable=name == 'slot_pick',
        produced_observations=(() if name != 'scores' else (ProducedObservation(
            output_port='scores', output_partition='raw', metric=Ref('metric', 'selection_fixture.raw'),
            context_profile=IntrinsicContextProfile(), subject_input='candidates', guaranteed_multiplicity='zero_or_more'),)),
    ) for name in ('candidates', 'scores', 'sequence_values', 'slot_pick', 'backbone'))
    return ModulePackageRegistration('selection_fixture', 'tests.selection_fixture',
        node_definitions=tuple(DefinitionResource(name + '.yaml') for name in ('candidates', 'scores', 'sequence_values', 'slot_pick', 'backbone')),
        metric_definitions=(DefinitionResource('raw.yaml'),), methods=methods, bindings=bindings)


class SelectionApplicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        registrations = (MODULE_PACKAGE, COLLECTIONS, study_registration()) + getattr(self, 'extra_registrations', ())
        catalog = build_frozen_catalog(registrations)
        projects = ProjectManager(root/'projects', cache_root=root/'cache', output_root=root/'outputs', run_root=root/'runs')
        authoring = WorkflowAuthoringService(projects, catalog)
        store = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
        runtime = V2RunService(projects, catalog, authoring,
            NodeAttemptFactory(projects, admit_environment_configuration(catalog, {}), store), store)
        self.client = TestClient(create_http_app(catalog, projects, authoring, runtime,
            authoring_projection=build_authoring_capability_projection(registrations, catalog)))
        self.client.__enter__()
        response = self.client.post('/api/v2/projects', json={'name': 'Raw selection'})
        self.assertEqual(response.status_code, 201, response.text)
        self.project = response.json()['id']

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def workflow(self):
        def node(identity, kind, parameters):
            return {'node_id': identity, 'node_type_id': kind, 'binding_id': kind + '.direct',
                    'node_parameters': parameters, 'binding_parameters': {}}
        return {'schema_version': '2.1.0', 'workflow_id': self.project, 'nodes': [
            node('population', 'selection_fixture.candidates', {}),
            node('measurements', 'selection_fixture.scores', {}),
            node('chosen', 'selection.top_k', {'selection': {
                'score_input': 'raw-score', 'metric_id': 'selection_fixture.raw',
                'method_id': 'selection_fixture.scores.method', 'source_partition': 'raw',
                'context': {'kind': 'intrinsic'}}, 'direction': 'descending', 'k': 1}),
        ], 'edges': [
            {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'measurements', 'target_port': 'candidates'},
            {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'chosen', 'target_port': 'candidates'},
            {'source_node_id': 'measurements', 'source_port': 'scores', 'target_node_id': 'chosen', 'target_port': 'scores', 'target_slot': 'raw-score'},
        ]}

    def execute_workflow(self, workflow):
        committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
        self.assertEqual(committed.status_code, 200, committed.text)
        started = self.client.post(f'/api/v2/projects/{self.project}/runs', json={
            'workflow_commit_id': committed.json()['workflow_commit_id'], 'client_request_id': 'study-run'})
        self.assertEqual(started.status_code, 202, started.text)
        run_id = started.json()['run_id']
        for _ in range(200):
            projection = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}').json()
            if projection['status'] not in ('admitted', 'running'):
                return run_id, projection
            time.sleep(0.01)
        self.fail('Study run did not finish')

    def pareto_workflow(self):
        workflow = self.workflow()
        first = workflow['nodes'][-1]['node_parameters']['selection']
        second = dict(first, score_input='cost-score')
        workflow['nodes'][1]['node_parameters'] = {'values': [12, 8, 6]}
        workflow['nodes'].insert(2, dict(workflow['nodes'][1], node_id='costs', node_parameters={'values': [9, 2, 5]}))
        workflow['edges'].extend([
            {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'costs', 'target_port': 'candidates'},
            {'source_node_id': 'costs', 'source_port': 'scores', 'target_node_id': 'chosen', 'target_port': 'scores', 'target_slot': 'cost-score'},
        ])
        workflow['nodes'][-1].update(node_type_id='selection.pareto', binding_id='selection.pareto.direct', node_parameters={
            'objectives': [{'selection': first, 'direction': 'descending'}, {'selection': second, 'direction': 'ascending'}]})
        return workflow

    def test_save_reopen_run_pareto_retains_original_non_dominated_candidates_in_input_order(self):
        workflow = self.pareto_workflow()
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = self.client.get(f'/api/v2/projects/{self.project}/workspace').json()['draft']['workflow']
        self.assertEqual(reopened['nodes'][-1]['node_parameters'], workflow['nodes'][-1]['node_parameters'])
        run_id, projection = self.execute_workflow(reopened)
        self.assertEqual(projection['status'], 'succeeded', projection)
        original = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/population/candidates/values/0').json()
        chosen = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0').json()
        self.assertEqual(chosen['value']['fields']['items'], original['value']['fields']['items'][:2])

    def test_pareto_missing_a_required_objective_stops_the_node(self):
        workflow = self.pareto_workflow()
        workflow['nodes'][2]['node_parameters']['values'] = [9, None, 5]
        _, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'failed', projection)
        self.assertEqual({item['node_id']: item['outcome'] for item in projection['node_dispositions']},
            {'population': 'succeeded', 'measurements': 'succeeded', 'costs': 'succeeded', 'chosen': 'failed'})

    def test_incomplete_or_legacy_pareto_settings_save_but_cannot_run(self):
        for change in ('missing_direction', 'disconnected_score', 'legacy'):
            with self.subTest(change=change):
                workflow = self.pareto_workflow()
                parameters = workflow['nodes'][-1]['node_parameters']
                if change == 'missing_direction':
                    del parameters['objectives'][1]['direction']
                elif change == 'disconnected_score':
                    workflow['edges'][-1]['target_slot'] = 'another-source'
                else:
                    workflow['nodes'][-1]['node_parameters'] = {'objective_ids': ['old-objective'], 'tie_policy': 'candidate_id_ascending'}
                saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
                self.assertEqual(saved.status_code, 200, saved.text)
                committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
                self.assertEqual(committed.status_code, 422, committed.text)

    def test_missing_required_evaluation_blocks_dependents_and_keeps_independent_results(self):
        workflow = self.workflow()
        workflow['nodes'][1]['node_parameters'] = {'values': [12, None, -8]}
        downstream = dict(workflow['nodes'][1], node_id='dependent', node_parameters={})
        independent = dict(workflow['nodes'][1], node_id='independent', node_parameters={})
        workflow['nodes'].extend([downstream, independent])
        workflow['edges'].extend([
            {'source_node_id': 'chosen', 'source_port': 'candidates', 'target_node_id': 'dependent', 'target_port': 'candidates'},
            {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'independent', 'target_port': 'candidates'},
        ])
        _, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'failed', projection)
        dispositions = {item['node_id']: item['outcome'] for item in projection['node_dispositions']}
        self.assertEqual(dispositions, {'population': 'succeeded', 'measurements': 'succeeded',
            'chosen': 'failed', 'dependent': 'blocked', 'independent': 'succeeded'})

    def test_top_k_returns_whole_small_or_empty_population(self):
        for count in (0, 2):
            with self.subTest(count=count):
                workflow = self.workflow()
                workflow['nodes'][0]['node_parameters']['count'] = count
                workflow['nodes'][-1]['node_parameters']['k'] = 5
                run_id, projection = self.execute_workflow(workflow)
                self.assertEqual(projection['status'], 'succeeded', projection)
                output = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0')
                self.assertEqual(output.status_code, 200, output.text)
                self.assertEqual(len(output.json()['value']['fields']['items']), count)

    def test_only_new_node_local_schema_can_be_committed(self):
        workflow = self.workflow()
        workflow['nodes'][-1]['node_parameters'] = {'objective_id': 'old-objective', 'k': 1}
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
        self.assertEqual(committed.status_code, 422, committed.text)

    def test_editor_can_choose_a_source_with_multiple_or_missing_observations(self):
        workflow = self.workflow()
        response = self.client.post(f'/api/v2/projects/{self.project}/workflow:observation-options',
            json={'workflow': {'nodes': workflow['nodes'], 'edges': workflow['edges']}, 'ranking': False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([(value['metric_id'], value['source']['node_id']) for value in response.json()['options']],
            [('selection_fixture.raw', 'measurements')])

    def test_cache_keeps_each_stable_slot_group_even_when_flattened_values_are_identical(self):
        def node(identity, kind, parameters):
            return {'node_id': identity, 'node_type_id': 'selection_fixture.' + kind,
                'binding_id': 'selection_fixture.' + kind + '.direct',
                'node_parameters': parameters, 'binding_parameters': {}}
        workflow = {'schema_version': '2.1.0', 'workflow_id': self.project,
            'nodes': [node('first', 'sequence_values', {'values': ['A']}),
                      node('second', 'sequence_values', {'values': ['C', 'D']}),
                      node('chosen', 'slot_pick', {'selected_slot': 'first-group'})],
            'edges': [{'source_node_id': identity, 'source_port': 'sequences', 'target_node_id': 'chosen',
                       'target_port': 'sequences', 'target_slot': slot}
                      for identity, slot in [('first', 'first-group'), ('second', 'second-group')]]}
        first_run, first_projection = self.execute_workflow(workflow)
        self.assertEqual(first_projection['status'], 'succeeded', first_projection)
        workflow['nodes'][0]['node_parameters']['values'] = ['A', 'C']
        workflow['nodes'][1]['node_parameters']['values'] = ['D']
        second_run, second_projection = self.execute_workflow(workflow)
        self.assertEqual(second_projection['status'], 'succeeded', second_projection)
        output = self.client.get(f'/api/v2/projects/{self.project}/runs/{second_run}/outputs/chosen/sequence/values/0')
        self.assertEqual(output.json()['value']['fields']['sequence'], 'AC')

    def test_inactive_parameter_alternative_does_not_require_an_input_slot(self):
        def node(identity, kind, parameters):
            return {'node_id': identity, 'node_type_id': 'selection_fixture.' + kind,
                'binding_id': 'selection_fixture.' + kind + '.direct',
                'node_parameters': parameters, 'binding_parameters': {}}
        workflow = {'schema_version': '2.1.0', 'workflow_id': self.project,
            'nodes': [node('values', 'sequence_values', {'values': ['A']}), node('chosen', 'slot_pick', {'selected_slot': {}})],
            'edges': [{'source_node_id': 'values', 'source_port': 'sequences', 'target_node_id': 'chosen',
                       'target_port': 'sequences', 'target_slot': 'available-values'}]}
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        output = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/sequence/values/0')
        self.assertEqual(output.json()['value']['fields']['sequence'], 'W')

    def test_workflow_connections_express_global_and_each_backbone_top_k(self):
        def node(identity, kind, parameters=None):
            return {'node_id': identity, 'node_type_id': kind, 'binding_id': kind + '.direct',
                    'node_parameters': parameters or {}, 'binding_parameters': {}}
        def edge(source, output, target, port, slot=None):
            return {'source_node_id': source, 'source_port': output, 'target_node_id': target, 'target_port': port,
                    **({'target_slot': slot} if slot else {})}
        workflow = self.workflow()
        selection = workflow['nodes'][-1]['node_parameters']['selection']
        workflow['nodes'] = [node('group-a', 'selection_fixture.candidates', {'count': 2}),
            node('group-b', 'selection_fixture.candidates', {'count': 1, 'start': 2}),
            node('backbone-a', 'selection_fixture.backbone', {'index': 0}),
            node('backbone-b', 'selection_fixture.backbone', {'index': 1}),
            node('population', 'collection_ops.concat_candidates'),
            node('relation-a', 'collection_ops.relate_to_single_reference'),
            node('relation-b', 'collection_ops.relate_to_single_reference'),
            node('relations', 'collection_ops.concat_relations'), node('measurements', 'selection_fixture.scores'),
            node('scope-a', 'collection_ops.select_related_subjects'), node('scope-b', 'collection_ops.select_related_subjects'),
            node('global', 'selection.top_k', {'selection': selection, 'direction': 'descending', 'k': 2}),
            node('per-a', 'selection.top_k', {'selection': selection, 'direction': 'descending', 'k': 1}),
            node('per-b', 'selection.top_k', {'selection': selection, 'direction': 'descending', 'k': 1})]
        workflow['edges'] = [edge('group-a', 'candidates', 'population', 'candidates_a'),
            edge('group-b', 'candidates', 'population', 'candidates_b'),
            edge('population', 'candidates', 'measurements', 'candidates'),
            edge('population', 'candidates', 'global', 'candidates')]
        for suffix in ('a', 'b'):
            workflow['edges'].extend([edge('group-' + suffix, 'candidates', 'relation-' + suffix, 'subjects'),
                edge('backbone-' + suffix, 'candidates', 'relation-' + suffix, 'references'),
                edge('relation-' + suffix, 'relation', 'relations', 'relation_' + suffix),
                edge('population', 'candidates', 'scope-' + suffix, 'subjects'),
                edge('backbone-' + suffix, 'candidates', 'scope-' + suffix, 'selected_references'),
                edge('relations', 'relation', 'scope-' + suffix, 'relation'),
                edge('scope-' + suffix, 'candidates', 'per-' + suffix, 'candidates')])
        workflow['edges'].extend(edge('measurements', 'scores', target, 'scores', 'raw-score') for target in ('global', 'per-a', 'per-b'))
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        selected = {}
        for identity in ('global', 'per-a', 'per-b'):
            output = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/{identity}/candidates/values/0')
            selected[identity] = [dict(item['fields']['metadata']['$map'])['display_name'] for item in output.json()['value']['fields']['items']]
        self.assertEqual(selected, {'global': ['zeta', 'alpha'], 'per-a': ['zeta'], 'per-b': ['last']})

    def test_disconnected_selected_score_slot_can_be_saved_but_cannot_run(self):
        workflow = self.workflow()
        workflow['edges'][-1]['target_slot'] = 'a-different-input'
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
        self.assertEqual(committed.status_code, 422, committed.text)
        self.assertIn('raw-score', committed.text)

    def test_save_reopen_and_run_node_owned_raw_top_k(self):
        workflow = self.workflow()
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = self.client.get(f'/api/v2/projects/{self.project}/workspace')
        self.assertEqual(reopened.json()['draft']['workflow']['nodes'][-1]['node_parameters'], workflow['nodes'][-1]['node_parameters'])
        committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertTrue(committed.json()['accepted'], committed.text)
        started = self.client.post(f'/api/v2/projects/{self.project}/runs', json={
            'workflow_commit_id': committed.json()['workflow_commit_id'], 'client_request_id': 'study-run'})
        self.assertEqual(started.status_code, 202, started.text)
        run_id = started.json()['run_id']
        for _ in range(200):
            projection = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}').json()
            if projection['status'] not in ('admitted', 'running'):
                break
            time.sleep(0.01)
        self.assertEqual(projection['status'], 'succeeded', projection)
        original = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/population/candidates/values/0')
        chosen = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0')
        self.assertEqual(chosen.status_code, 200, chosen.text)
        self.assertEqual(chosen.json()['value']['fields']['items'], original.json()['value']['fields']['items'][:1])
        workflow['nodes'][-1]['node_parameters']['direction'] = 'ascending'
        ascending_run, ascending_projection = self.execute_workflow(workflow)
        self.assertEqual(ascending_projection['status'], 'succeeded', ascending_projection)
        minimum = self.client.get(f'/api/v2/projects/{self.project}/runs/{ascending_run}/outputs/chosen/candidates/values/0')
        self.assertEqual(minimum.json()['value']['fields']['items'], original.json()['value']['fields']['items'][-1:])


if __name__ == '__main__':
    unittest.main()
