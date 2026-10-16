"""Saved weighted Selection exercised through the public application interface."""
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from dataclasses import replace
import json

from fastapi.testclient import TestClient
from core.catalog.authoring import build_authoring_capability_projection
from core.catalog.builder import build_frozen_catalog
from core.catalog.declarations import MethodDefinition
from core.catalog.port_contract import BehaviorReference
from datatypes.exact_reference import ExactContractReference as Ref
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.results.cache import ProjectReplayIndex
from core.execution.results.store import ResultStore
from core.execution.runtime import V2RunService
from core.project.manager import ProjectManager
from core.project.objects import ProjectObjectStore
from core.workflow.authoring import WorkflowAuthoringService
from modules.selection.package import MODULE_PACKAGE
from protein_workbench_public.http.app import create_http_app
from tests.scoring_fixture import registration
from modules.selection.weighted import weighted_scores


class WeightedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.open_application()
        self.project = self.client.post('/api/v2/projects', json={'name': 'Weighted trials'}).json()['id']

    def open_application(self, external=None, selection=None):
        registrations = (selection or MODULE_PACKAGE, external or registration())
        catalog = build_frozen_catalog(registrations)
        projects = ProjectManager(self.root/'projects', cache_root=self.root/'cache', output_root=self.root/'outputs', run_root=self.root/'runs')
        authoring = WorkflowAuthoringService(projects, catalog)
        store = ResultStore(ProjectObjectStore(projects), ProjectReplayIndex(projects))
        runtime = V2RunService(projects, catalog, authoring,
            NodeAttemptFactory(projects, admit_environment_configuration(catalog, {}), store), store)
        self.client = TestClient(create_http_app(catalog, projects, authoring, runtime,
            authoring_projection=build_authoring_capability_projection(registrations, catalog)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def workflow(self, weights=(1, 3)):
        def node(identity, kind, parameters):
            return {'node_id': identity, 'node_type_id': kind, 'binding_id': kind+'.direct',
                    'node_parameters': parameters, 'binding_parameters': {}}
        def selection(slot):
            return {'score_input': slot, 'metric_id': 'scoring_fixture.success_fraction',
                    'method_id': 'scoring_fixture.trials', 'source_partition': 'trials', 'context': {'kind': 'intrinsic'}}
        return {'schema_version': '2.1.0', 'workflow_id': self.project, 'nodes': [
            node('population', 'scoring_fixture.population', {}),
            node('first', 'scoring_fixture.measurements', {'values': [0.9, 0.1, 0.5]}),
            node('second', 'scoring_fixture.measurements', {'values': [0.1, 0.9, 0.5]}),
            node('rank', 'selection.weighted_rank', {'objectives': [
                {'selection': selection(slot), 'transform_id': 'scoring_fixture.success_fraction.native', 'weight': weight}
                for slot, weight in zip(('first', 'second'), weights, strict=True)]}),
        ], 'edges': [
            {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': target, 'target_port': 'candidates'}
            for target in ('first', 'second', 'rank')
        ] + [
            {'source_node_id': slot, 'source_port': 'scores', 'target_node_id': 'rank', 'target_port': 'scores', 'target_slot': slot}
            for slot in ('first', 'second')
        ]}

    def execute(self, workflow):
        committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertTrue(committed.json()['accepted'], committed.text)
        response = self.client.post(f'/api/v2/projects/{self.project}/runs', json={
            'workflow_commit_id': committed.json()['workflow_commit_id'], 'client_request_id': 'trial'})
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()['run_id']
        for _ in range(200):
            response = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}')
            self.assertEqual(response.status_code, 200, response.text)
            projection = response.json()
            if projection['status'] not in ('admitted', 'running'):
                return run_id, projection
            time.sleep(0.01)
        self.fail('Trial run did not finish')

    def output(self, run_id, node='rank', port='candidates'):
        response = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/{node}/{port}/values/0')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['value']['fields']['items']

    def test_save_reopen_and_run_weighted_choices_preserves_original_values_and_observations(self):
        workflow = self.workflow()
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = self.client.get(f'/api/v2/projects/{self.project}/workspace').json()['draft']['workflow']
        run_id, projection = self.execute(reopened)
        self.assertEqual(projection['status'], 'succeeded', projection)
        original = self.output(run_id, 'population')
        self.assertEqual(self.output(run_id), [original[1], original[2], original[0]])
        scores = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/first/scores/values/0').json()
        self.assertEqual([item['fields']['value'] for item in scores['value']['fields']['entries']], [0.9, 0.1, 0.5])

    def test_zero_weight_does_not_require_scores_connected_slots_or_existing_definitions(self):
        workflow = self.workflow((0, 1))
        objective = workflow['nodes'][-1]['node_parameters']['objectives'][0]
        objective['transform_id'] = 'removed.unused.transform'
        objective['selection'].update(metric_id='removed.metric', method_id='removed.method', score_input='disconnected')
        workflow['nodes'][1]['node_parameters']['values'] = [None, None, None]
        workflow['edges'] = [edge for edge in workflow['edges'] if edge.get('target_slot') != 'first']
        run_id, projection = self.execute(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        original = self.output(run_id, 'population')
        self.assertEqual(self.output(run_id), [original[1], original[2], original[0]])

    def test_proportional_and_large_finite_weights_preserve_ties_in_input_order(self):
        for weights in ((1, 1), (9, 9), (1e308, 1e308)):
            with self.subTest(weights=weights):
                run_id, projection = self.execute(self.workflow(weights))
                self.assertEqual(projection['status'], 'succeeded', projection)
                self.assertEqual(self.output(run_id), self.output(run_id, 'population'))

    def test_weighted_scores_are_a_normalized_mean(self):
        self.assertEqual(weighted_scores(((0.0, 1.0), (1.0, 0.0)), (1.0, 3.0)), (0.75, 0.25))

    def test_negative_or_all_zero_weights_cannot_run_but_incomplete_work_can_be_saved(self):
        for weights in ((0, 0), (-1, 2)):
            with self.subTest(weights=weights):
                workflow = self.workflow(weights)
                saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
                self.assertEqual(saved.status_code, 200, saved.text)
                committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
                self.assertEqual(committed.status_code, 422, committed.text)
                self.assertIn('weight', committed.text.lower())

    def test_missing_or_ambiguous_active_evaluation_stops_weighted_ranking(self):
        workflow = self.workflow()
        workflow['nodes'][1]['node_parameters']['values'] = [0.9, None, 0.5]
        _, projection = self.execute(workflow)
        self.assertEqual(projection['status'], 'failed', projection)
        self.assertEqual(next(item['outcome'] for item in projection['node_dispositions'] if item['node_id'] == 'rank'), 'failed')

    def test_changed_transform_behavior_is_used_instead_of_replaying_the_old_ranking(self):
        workflow = self.workflow()
        first_run, _ = self.execute(workflow)
        base = registration()
        transform = replace(base.utility_transforms[0],
            behavior=BehaviorReference('scoring_fixture/native', {'mapping': 'failure-fraction'}),
            transform=lambda value, parameters: 1.0-float(value))
        self.open_application(replace(base, utility_transforms=(transform,)))
        second_run, projection = self.execute(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        self.assertEqual(self.output(second_run), list(reversed(self.output(first_run))))
        self.assertEqual(next(item['resolution'] for item in projection['node_dispositions'] if item['node_id'] == 'rank'), 'executed')

    def test_changed_module_default_is_admitted_and_changes_the_ranking(self):
        base = registration()
        def version(reverse):
            return replace(base, utility_transforms=(replace(base.utility_transforms[0],
                parameters={'reverse': {'parameter_scope': 'scientific', 'scientific_meaning': 'Use the recorded failure fraction.',
                    'required': True, 'default': reverse, 'value_contract': {'type': 'boolean'}}},
                transform=lambda value, parameters: 1.0-float(value) if parameters['reverse'] else float(value)),))
        self.open_application(version(False))
        workflow = self.workflow()
        first_run, _ = self.execute(workflow)
        self.open_application(version(True))
        second_run, projection = self.execute(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        self.assertEqual(self.output(second_run), list(reversed(self.output(first_run))))

    def test_changed_applicability_fails_instead_of_replaying_a_previous_success(self):
        workflow = self.workflow()
        _, first_projection = self.execute(workflow)
        self.assertEqual(first_projection['status'], 'succeeded', first_projection)
        base = registration()
        transform = replace(base.utility_transforms[0], compatible_input_contract={
            **base.utility_transforms[0].compatible_input_contract, 'context_profile': {'kind': 'calibration'}})
        self.open_application(replace(base, utility_transforms=(transform,)))
        _, projection = self.execute(workflow)
        self.assertEqual(projection['status'], 'failed', projection)
        self.assertEqual(next(item['outcome'] for item in projection['node_dispositions'] if item['node_id'] == 'rank'), 'failed')

    def test_recursive_used_definition_changes_cannot_replay_previous_results(self):
        base = registration()
        leaf = Ref('method', 'scoring_fixture.measurement_basis')
        middle = MethodDefinition('scoring_fixture.scoring_basis', {'measurement': leaf}, {}, {}, {})
        transform = replace(base.utility_transforms[0], compatible_input_contract={
            **base.utility_transforms[0].compatible_input_contract,
            'scoring_basis': Ref('method', middle.method_id)})
        def version(trials):
            return replace(base, methods=base.methods+(middle,
                MethodDefinition(leaf.contract_id, {'recorded_trial_count': trials}, {}, {}, {})),
                utility_transforms=(transform,))
        self.open_application(version(10))
        workflow = self.workflow()
        self.execute(workflow)
        _, same_projection = self.execute(workflow)
        self.assertEqual(next(item['resolution'] for item in same_projection['node_dispositions'] if item['node_id'] == 'rank'), 'cache_replayed')
        self.open_application(version(20))
        _, changed_projection = self.execute(workflow)
        self.assertEqual(changed_projection['status'], 'succeeded', changed_projection)
        self.assertEqual(next(item['resolution'] for item in changed_projection['node_dispositions'] if item['node_id'] == 'rank'), 'executed')

    def test_removed_zero_weight_transform_does_not_invalidate_the_active_ranking(self):
        base = registration()
        unused = replace(base.utility_transforms[0], transform_id='scoring_fixture.unused')
        self.open_application(replace(base, utility_transforms=base.utility_transforms+(unused,)))
        workflow = self.workflow((0, 1))
        workflow['nodes'][-1]['node_parameters']['objectives'][0]['transform_id'] = unused.transform_id
        first_run, _ = self.execute(workflow)
        self.open_application(base)
        second_run, projection = self.execute(workflow)
        self.assertEqual(self.output(second_run), self.output(first_run))
        self.assertEqual(next(item['resolution'] for item in projection['node_dispositions'] if item['node_id'] == 'rank'), 'cache_replayed')

    def test_raw_operations_do_not_resolve_or_require_any_scoring_transform(self):
        base = registration()
        self.open_application(replace(base, utility_transforms=()))
        for operation, parameters in (
            ('sort', {'direction': 'descending'}),
            ('filter', {'condition': {'kind': 'comparison', 'operator': '>=', 'threshold': 0.5}}),
            ('pareto', {'objectives': []}),
        ):
            with self.subTest(operation=operation):
                workflow = self.workflow()
                selected = workflow['nodes'][-1]['node_parameters']['objectives'][0]['selection']
                if operation == 'filter':
                    parameters['condition']['selection'] = selected
                elif operation == 'pareto':
                    parameters['objectives'] = [{'selection': selected, 'direction': 'descending'}]
                else:
                    parameters['selection'] = selected
                workflow['nodes'][-1].update(node_type_id='selection.'+operation,
                    binding_id='selection.'+operation+'.direct', node_parameters=parameters)
                _, projection = self.execute(workflow)
                self.assertEqual(projection['status'], 'succeeded', projection)

    def test_nonfinite_weights_are_rejected_at_the_public_request_boundary(self):
        for value in (float('inf'), -float('inf'), float('nan')):
            with self.subTest(value=value):
                workflow = self.workflow((value, 1))
                response = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit',
                    content=json.dumps({'workflow': workflow}), headers={'content-type': 'application/json'})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn('finite', response.text)

    def test_binding_factory_and_parameter_resolver_behavior_changes_invalidate_the_cache(self):
        workflow = self.workflow()
        self.execute(workflow)
        for declaration in ('factory', 'parameter_dependencies'):
            with self.subTest(declaration=declaration):
                bindings = tuple(replace(binding, **{declaration: replace(getattr(binding, declaration),
                    behavior=BehaviorReference(f'selection.weighted_rank/{declaration}', {'revision': 2}))})
                    if binding.binding_id == 'selection.weighted_rank.direct' else binding for binding in MODULE_PACKAGE.bindings)
                self.open_application(selection=replace(MODULE_PACKAGE, bindings=bindings))
                _, projection = self.execute(workflow)
                self.assertEqual(projection['status'], 'succeeded', projection)
                self.assertEqual(next(item['resolution'] for item in projection['node_dispositions'] if item['node_id'] == 'rank'), 'executed')

    def test_unfinished_zero_weight_terms_do_not_block_a_configured_active_term(self):
        for term in ({'weight': 0}, {'weight': 0, 'transform_id': '', 'selection': {
            'score_input': '', 'metric_id': '', 'method_id': '', 'source_partition': '', 'context': {}}}):
            with self.subTest(term=term):
                workflow = self.workflow((0, 1))
                workflow['nodes'][-1]['node_parameters']['objectives'][0] = term
                run_id, projection = self.execute(workflow)
                self.assertEqual(projection['status'], 'succeeded', projection)
                original = self.output(run_id, 'population')
                self.assertEqual(self.output(run_id), [original[1], original[2], original[0]])

    def test_scoring_title_changes_keep_the_existing_result_identity(self):
        workflow = self.workflow()
        self.execute(workflow)
        base = registration()
        transform = replace(base.utility_transforms[0], title='Renamed presentation only')
        self.open_application(replace(base, utility_transforms=(transform,)))
        _, projection = self.execute(workflow)
        self.assertEqual(next(item['resolution'] for item in projection['node_dispositions'] if item['node_id'] == 'rank'), 'cache_replayed')


if __name__ == '__main__':
    unittest.main()
