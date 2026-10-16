"""Public module authoring action for unfinished Selection workflows."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from core.catalog.authoring import build_authoring_capability_projection
from core.catalog.builder import build_frozen_catalog
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.execution.runtime import V2RunService
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from modules.collection_ops.package import MODULE_PACKAGE as COLLECTIONS
from modules.selection.package import MODULE_PACKAGE
from modules.structure_prediction.package import MODULE_PACKAGE as CONFIDENCE
from protein_workbench_public.http.app import create_http_app
from tests import test_selection_application as study
from modules.selection.tests.authoring_fixture import registration as authoring_registration


class SelectionAuthoringTests(unittest.TestCase):
    execute_workflow = study.SelectionApplicationTests.execute_workflow

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        registrations = (MODULE_PACKAGE, COLLECTIONS, study.study_registration(), CONFIDENCE, authoring_registration()) + getattr(self, 'extra_registrations', ())
        catalog = build_frozen_catalog(registrations)
        projects = ProjectManager(root/'projects', cache_root=root/'cache', output_root=root/'outputs', run_root=root/'runs')
        authoring = WorkflowAuthoringService(projects, catalog)
        store = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
        runtime = V2RunService(projects, catalog, authoring,
            NodeAttemptFactory(projects, admit_environment_configuration(catalog, {}), store), store)
        self.addCleanup(runtime.shutdown)
        self.client = TestClient(create_http_app(catalog, projects, authoring, runtime,
            authoring_projection=build_authoring_capability_projection(registrations, catalog)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.project = self.client.post('/api/v2/projects', json={'name': 'Selection editor'}).json()['id']

    @staticmethod
    def node(identity, kind, parameters=None):
        return {'node_id': identity, 'node_type_id': kind, 'binding_id': kind + '.direct',
                'node_parameters': parameters or {}, 'binding_parameters': {}}

    def options(self, nodes, edges=(), *, ranking=True, prospective_inputs=()):
        return self.client.post(f'/api/v2/projects/{self.project}/authoring-actions/selection.observation_options',
            json={'parameters': {'workflow': {'nodes': nodes, 'edges': list(edges)}, 'ranking': ranking},
                  'prospective_inputs': list(prospective_inputs)})

    def test_unfinished_raw_pareto_and_weighted_editors_offer_external_measurements_before_any_run(self):
        for operation in ('filter', 'sort', 'top_k', 'pareto', 'weighted_rank'):
            with self.subTest(operation=operation):
                response = self.options([
                    self.node('observed', 'selection_fixture.scores'),
                    self.node('chosen', 'selection.' + operation),
                ], ranking=operation != 'filter')
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), {'options': [{
                    'source': {'node_id': 'observed', 'output_port': 'scores'}, 'partition': 'raw',
                    'metric_id': 'selection_fixture.raw', 'method_id': 'selection_fixture.scores.method',
                    'context': {'kind': 'intrinsic'}}]})

    def test_manual_selection_is_an_ordinary_typed_operation_preserving_exact_input_candidates(self):
        population = self.node('population', 'selection_fixture.candidates')
        scores = self.node('measurements', 'selection_fixture.scores')
        source = {'schema_version': '2.1.0', 'workflow_id': self.project, 'nodes': [population, scores], 'edges': [
            {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'measurements', 'target_port': 'candidates'}]}
        run_id, projection = self.execute_workflow(source)
        self.assertEqual(projection['status'], 'succeeded', projection)
        original = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/population/candidates/values/0').json()['value']['fields']['items']
        scores = self.client.post(f'/api/v2/projects/{self.project}/runs/{run_id}/results:value',
            json={'node_id': 'measurements', 'output_port': 'scores', 'value_index': 0}).json()['value']['entries']
        references = [score['subject'] for score in scores]
        workflow = {'schema_version': '2.1.0', 'workflow_id': self.project,
            'nodes': [population, self.node('chosen', 'selection.manual', {'selected_candidates': [references[2], references[0]]})],
            'edges': [{'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'chosen', 'target_port': 'candidates'}]}
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        chosen = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0').json()['value']['fields']['items']
        self.assertEqual(chosen, [original[0], original[2]])
        self.assertNotIn('selection_results', projection)
        self.assertNotIn('selection_error', projection)
        event_types = []
        with self.client.websocket_connect(f'/api/v2/projects/{self.project}/runs/{run_id}/events') as stream:
            while True:
                event = stream.receive_json()['event']
                event_types.append(event['type'])
                if event['type'] == 'replay_complete':
                    break
        self.assertNotIn('selection_terminal', event_types)

    def test_unknown_and_unavailable_adopted_nodes_do_not_block_known_observation_options(self):
        response = self.options([
            self.node('observed', 'selection_fixture.scores'),
            self.node('unknown', 'outside.not_installed', {'saved': 'keep'}),
            self.node('unavailable', 'selection.adopt_scores', {'project_input_ref': 'missing-input'}),
        ])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item['source']['node_id'] for item in response.json()['options']], ['observed'])

    def test_external_method_source_and_union_pass_through_filter_preserve_original_meaning(self):
        nodes = [self.node('observed', 'selection_fixture.scores'), self.node('producer', 'authoring_fixture.source'),
            self.node('materialized', 'authoring_fixture.proxy'),
            self.node('merged', 'collection_ops.merge_scores'),
            self.node('passed', 'authoring_fixture.pass'), self.node('filtered', 'authoring_fixture.filtered')]
        def edge(source, target, port):
            return {'source_node_id': source, 'source_port': 'scores', 'target_node_id': target, 'target_port': port}
        edges = [{'source_node_id': 'producer', 'source_port': 'facts', 'target_node_id': 'materialized', 'target_port': 'confidence_facts'},
            edge('observed', 'merged', 'scores_a'), edge('observed', 'merged', 'scores_b'),
            edge('materialized', 'merged', 'scores_c'), edge('merged', 'passed', 'scores'),
            edge('passed', 'filtered', 'scores')]
        response = self.options(nodes, edges)
        self.assertEqual(response.status_code, 200, response.text)
        meanings = [(item['source']['node_id'], item['partition'], item['method_id']) for item in response.json()['options']]
        self.assertEqual(meanings, [
            ('observed', 'raw', 'selection_fixture.scores.method'),
            ('materialized', 'preserved', 'authoring_fixture.source.method'),
            ('merged', 'raw', 'selection_fixture.scores.method'),
            ('merged', 'preserved', 'authoring_fixture.source.method'),
            ('passed', 'raw', 'selection_fixture.scores.method'),
            ('passed', 'preserved', 'authoring_fixture.source.method'),
            ('filtered', 'preserved', 'authoring_fixture.source.method')])
        disconnected = self.options(nodes, edges[1:])
        self.assertEqual(disconnected.status_code, 200, disconnected.text)
        self.assertFalse(any(item['partition'] == 'preserved' for item in disconnected.json()['options']))

    def test_saved_and_prospective_adopted_scores_offer_original_options_after_source_deletion(self):
        import base64
        import json

        source_project = self.project
        workflow = study.SelectionApplicationTests.workflow(self)
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        raw = self.client.get(f'/api/v2/projects/{source_project}/runs/{run_id}/outputs/measurements/scores/values/0')
        entries = self.client.post(f'/api/v2/projects/{source_project}/runs/{run_id}/results:value',
            json={'node_id': 'measurements', 'output_port': 'scores', 'value_index': 0}).json()['value']['entries']
        self.project = self.client.post('/api/v2/projects', json={'name': 'Adopted measurements'}).json()['id']
        adopted = self.client.post(f'/api/v2/projects/{self.project}/inputs:adopt', json={
            'source_project_id': source_project, 'source_run_id': run_id,
            'node_id': 'measurements', 'output_port': 'scores', 'value_index': 0})
        self.assertEqual(adopted.status_code, 201, adopted.text)
        saved = adopted.json()
        metadata = self.client.get(f'/api/v2/projects/{self.project}/inputs/{saved["project_input_ref"]}:adoption').json()
        snapshot = {**metadata, 'port_type_id': 'score.collection', 'canonical_value': raw.text,
            'content_digest': raw.headers['Digest'], 'candidate_data': [entry['subject'] for entry in entries], 'axis_digests': []}
        self.assertEqual(self.client.post(f'/api/v2/projects/{source_project}:trash').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/v2/projects/{source_project}').status_code, 200)
        source = {'node_id': 'history', **saved['source_node']}
        response = self.options([source])
        self.assertEqual(response.status_code, 200, response.text)
        expected = {'options': [{'source': {'node_id': 'history', 'output_port': 'value'}, 'partition': 'raw',
            'metric_id': 'selection_fixture.raw', 'method_id': 'selection_fixture.scores.method', 'context': {'kind': 'intrinsic'}}]}
        self.assertEqual(response.json(), expected)
        prospective = self.node('history', 'selection.adopt_scores', {'project_input_ref': 'prospective-scores'})
        before = self.client.get(f'/api/v2/projects/{self.project}/inputs').json()
        response = self.options([prospective], prospective_inputs=[{'project_input_ref': 'prospective-scores',
            'filename': 'scores.json', 'content_base64': base64.b64encode(json.dumps(snapshot).encode()).decode()}])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), expected)
        self.assertEqual(self.client.get(f'/api/v2/projects/{self.project}/inputs').json(), before)

    def test_manual_empty_selection_returns_an_empty_collection_for_empty_and_nonempty_inputs(self):
        for count in (0, 3):
            with self.subTest(count=count):
                workflow = {'schema_version': '2.1.0', 'workflow_id': self.project,
                    'nodes': [self.node('population', 'selection_fixture.candidates', {'count': count}),
                        self.node('chosen', 'selection.manual', {'selected_candidates': []})],
                    'edges': [{'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'chosen', 'target_port': 'candidates'}]}
                run_id, projection = self.execute_workflow(workflow)
                self.assertEqual(projection['status'], 'succeeded', projection)
                output = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0')
                self.assertEqual(output.status_code, 200, output.text)
                self.assertEqual(output.json()['value']['fields']['items'], [])

    def test_manual_missing_or_changed_exact_reference_is_an_ordinary_node_failure(self):
        source = study.SelectionApplicationTests.workflow(self)
        run_id, projection = self.execute_workflow(source)
        self.assertEqual(projection['status'], 'succeeded', projection)
        reference = self.client.post(f'/api/v2/projects/{self.project}/runs/{run_id}/results:value',
            json={'node_id': 'measurements', 'output_port': 'scores', 'value_index': 0}).json()['value']['entries'][0]['subject']
        for wrong in (dict(reference, content_digest='sha256:' + '0' * 64), dict(reference, candidate_id='absent')):
            with self.subTest(reference=wrong):
                workflow = {'schema_version': '2.1.0', 'workflow_id': self.project,
                    'nodes': [self.node('population', 'selection_fixture.candidates'),
                        self.node('chosen', 'selection.manual', {'selected_candidates': [wrong]}),
                        self.node('dependent', 'selection_fixture.scores'), self.node('independent', 'selection_fixture.candidates')],
                    'edges': [{'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'chosen', 'target_port': 'candidates'},
                        {'source_node_id': 'chosen', 'source_port': 'candidates', 'target_node_id': 'dependent', 'target_port': 'candidates'}]}
                run_id, projection = self.execute_workflow(workflow)
                self.assertEqual(projection['status'], 'failed', projection)
                self.assertEqual({item['node_id']: item['outcome'] for item in projection['node_dispositions']},
                    {'population': 'succeeded', 'chosen': 'failed', 'dependent': 'blocked', 'independent': 'succeeded'})
                with self.client.websocket_connect(f'/api/v2/projects/{self.project}/runs/{run_id}/events') as stream:
                    while True:
                        event = stream.receive_json()['event']
                        if event['type'] == 'node_attempt_terminal' and event['status'] == 'failed':
                            diagnostic = event['error']['details']['operation_diagnostic']
                            self.assertEqual(diagnostic['code'], 'missing_candidate_reference')
                            self.assertEqual(diagnostic['first_missing_candidate_reference'], wrong)
                            break
                        if event['type'] == 'replay_complete':
                            self.fail('No ordinary failed node attempt')

    def test_confidence_options_keep_scalar_metrics_and_the_upstream_prediction_method(self):
        nodes = [self.node('prediction', 'authoring_fixture.source'),
            self.node('confidence', 'structure_prediction.materialize_confidence')]
        response = self.options(nodes, [{'source_node_id': 'prediction', 'source_port': 'facts',
            'target_node_id': 'confidence', 'target_port': 'confidence_facts'}])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([(item['metric_id'], item['method_id']) for item in response.json()['options']],
            [('structure.ptm', 'authoring_fixture.source.method'),
             ('structure.plddt.mean_residue', 'authoring_fixture.source.method')])
