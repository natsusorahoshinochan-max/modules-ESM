"""Temporary Selection through the same public application boundary as nodes."""
import unittest

from tests import test_selection_application as scenarios
from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO
from tests.result_action_fixture import MODULE_PACKAGE as COMPARISONS


class ResultActionApplicationTests(unittest.TestCase):
    extra_registrations = (PROTEIN_IO, COMPARISONS)
    setUp = scenarios.SelectionApplicationTests.setUp
    tearDown = scenarios.SelectionApplicationTests.tearDown
    workflow = scenarios.SelectionApplicationTests.workflow
    execute_workflow = scenarios.SelectionApplicationTests.execute_workflow

    def action(self, run_id, parameters, **input_overrides):
        inputs = {
            'candidates': [{'node_id': 'population', 'output_port': 'candidates', 'value_index': 0, 'slot': 'population'}],
            'scores': [{'node_id': 'measurements', 'output_port': 'scores', 'value_index': 0, 'slot': 'raw-score'}],
            **input_overrides,
        }
        return self.client.post(f'/api/v2/projects/{self.project}/runs/{run_id}/results:action',
            json={'action_id': 'selection.view', 'inputs': inputs, 'parameters': parameters})

    def node_failure_message(self, run_id, node_id):
        with self.client.websocket_connect(f'/api/v2/projects/{self.project}/runs/{run_id}/events') as stream:
            while True:
                event = stream.receive_json()['event']
                if event['type'] == 'node_attempt_terminal' and event['status'] == 'failed':
                    return event['error']['message']
                if event['type'] == 'replay_complete':
                    self.fail(f'No public failure for {node_id}')

    def test_temporary_raw_sort_matches_node_order_without_creating_a_run(self):
        workflow = self.workflow()
        workflow['nodes'][-1]['node_type_id'] = 'selection.sort'
        workflow['nodes'][-1]['binding_id'] = 'selection.sort.direct'
        parameters = workflow['nodes'][-1]['node_parameters']
        del parameters['k']
        parameters['direction'] = 'ascending'
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        before = self.client.get(f'/api/v2/projects/{self.project}/runs').json()
        response = self.action(run_id, {'sort': parameters})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'candidate_indices': [2, 0, 1]})
        self.assertEqual(self.client.get(f'/api/v2/projects/{self.project}/runs').json(), before)

    def test_temporary_selection_matches_nodes_for_a_whole_collection_larger_than_a_page(self):
        workflow = self.workflow()
        workflow['nodes'][0]['node_parameters'] = {'count': 105}
        workflow['nodes'][1]['node_parameters'] = {'values': [index // 2 for index in range(105)]}
        selection = workflow['nodes'][-1]['node_parameters']['selection']
        condition = {'kind': 'comparison', 'selection': selection, 'operator': '>=', 'threshold': 50}
        workflow['nodes'][-1].update(node_type_id='selection.filter', binding_id='selection.filter.direct',
                                    node_parameters={'condition': condition})
        workflow['nodes'].append({'node_id': 'sorted', 'node_type_id': 'selection.sort',
            'binding_id': 'selection.sort.direct', 'node_parameters': {'selection': selection, 'direction': 'descending'}, 'binding_parameters': {}})
        workflow['edges'].extend([
            {'source_node_id': 'chosen', 'source_port': 'candidates', 'target_node_id': 'sorted', 'target_port': 'candidates'},
            {'source_node_id': 'measurements', 'source_port': 'scores', 'target_node_id': 'sorted', 'target_port': 'scores', 'target_slot': 'raw-score'}])
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        before_workspace = self.client.get(f'/api/v2/projects/{self.project}/workspace').json()
        before_run = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}').json()
        response = self.action(run_id, {'condition': condition, 'sort': {'selection': selection, 'direction': 'descending'}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'candidate_indices': [104, 102, 103, 100, 101]})
        original = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/population/candidates/values/0').json()['value']['fields']['items']
        chosen = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/sorted/candidates/values/0').json()['value']['fields']['items']
        self.assertEqual(chosen, [original[index] for index in response.json()['candidate_indices']])
        self.assertEqual(self.client.get(f'/api/v2/projects/{self.project}/workspace').json(), before_workspace)
        self.assertEqual(self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}').json(), before_run)

    def test_missing_required_measurement_reports_the_same_reason_as_the_node(self):
        workflow = self.workflow()
        workflow['nodes'][1]['node_parameters'] = {'values': [12, None, -8]}
        parameters = workflow['nodes'][-1]['node_parameters']
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'failed', projection)
        response = self.action(run_id, {'sort': {key: value for key, value in parameters.items() if key != 'k'}})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn('needs exactly one selected evaluation; found 0', response.json()['error']['message'])
        self.assertEqual(self.node_failure_message(run_id, 'chosen'), response.json()['error']['message'])

    def test_sort_only_requires_measurements_for_candidates_kept_by_the_filter(self):
        workflow = self.workflow()
        selection = workflow['nodes'][-1]['node_parameters']['selection']
        condition = {'kind': 'comparison', 'selection': selection, 'operator': '>=', 'threshold': 10}
        workflow['nodes'][-1].update(node_type_id='selection.filter', binding_id='selection.filter.direct', node_parameters={'condition': condition})
        sorting = {'selection': dict(selection, score_input='sort-score'), 'direction': 'descending'}
        workflow['nodes'].extend([
            dict(workflow['nodes'][1], node_id='partial-scores', node_parameters={'values': [1, 3, None]}),
            {'node_id': 'sorted', 'node_type_id': 'selection.sort', 'binding_id': 'selection.sort.direct',
             'node_parameters': sorting, 'binding_parameters': {}}])
        workflow['edges'].extend([
            {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'partial-scores', 'target_port': 'candidates'},
            {'source_node_id': 'chosen', 'source_port': 'candidates', 'target_node_id': 'sorted', 'target_port': 'candidates'},
            {'source_node_id': 'partial-scores', 'source_port': 'scores', 'target_node_id': 'sorted', 'target_port': 'scores', 'target_slot': 'sort-score'}])
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        response = self.action(run_id, {'condition': condition, 'sort': sorting}, scores=[
            {'node_id': node, 'output_port': 'scores', 'value_index': 0, 'slot': slot}
            for node, slot in [('measurements', 'raw-score'), ('partial-scores', 'sort-score')]])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'candidate_indices': [1, 0]})

    def test_read_failure_returns_no_partial_selection_and_can_be_retried(self):
        run_id, projection = self.execute_workflow(self.workflow())
        self.assertEqual(projection['status'], 'succeeded', projection)
        missing = self.action(run_id, {}, candidates=[{'node_id': 'population', 'output_port': 'candidates', 'value_index': 9, 'slot': 'population'}])
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertNotIn('candidate_indices', missing.json())
        retried = self.action(run_id, {})
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json(), {'candidate_indices': [0, 1, 2]})

    def test_candidate_page_action_uses_the_same_named_input_protocol(self):
        workflow = self.workflow()
        workflow['nodes'][0]['node_parameters'] = {'count': 105}
        workflow['nodes'][1]['node_parameters'] = {'values': list(range(105))}
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        path = f'/api/v2/projects/{self.project}/runs/{run_id}/results:action'
        response = self.client.post(path, json={'action_id': 'protein_io.candidate_page',
            'inputs': {'candidates': [{'node_id': 'population', 'output_port': 'candidates', 'value_index': 0, 'slot': 'collection'}]},
            'parameters': {'offset': 100, 'limit': 100}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()['total'], [entry['item_index'] for entry in response.json()['items']]),
                         (105, [100, 101, 102, 103, 104]))

    def test_existing_structure_read_and_export_actions_accept_declared_named_inputs(self):
        workflow = self.workflow()
        workflow['nodes'].append({'node_id': 'backbone', 'node_type_id': 'selection_fixture.backbone',
            'binding_id': 'selection_fixture.backbone.direct', 'node_parameters': {'index': 0}, 'binding_parameters': {}})
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        path = f'/api/v2/projects/{self.project}/runs/{run_id}/results:action'
        inputs = {'candidates': [{'node_id': 'backbone', 'output_port': 'candidates', 'value_index': 0, 'slot': 'collection'}]}
        for action, parameters in [('protein_io.candidate_structure', {'item_index': 0}),
                                   ('protein_io.export_structure', {'item_index': 0, 'format': 'mmcif'}),
                                   ('protein_io.structure_components', {'item_index': 0}),
                                   ('protein_io.export_structure_components', {'item_index': 0, 'component_indices': [1], 'format': 'pdb'})]:
            with self.subTest(action=action):
                response = self.client.post(path, json={'action_id': action, 'inputs': inputs, 'parameters': parameters})
                self.assertEqual(response.status_code, 200, response.text)
                if action == 'protein_io.structure_components':
                    self.assertEqual([(item['residue_name'], item['atom_count']) for item in response.json()['components']], [('ALA', 1)])
                else:
                    self.assertIn(response.json()['format'], ['pdb', 'mmcif'])
                    self.assertIn('ALA', response.json()['text'])

    def test_external_module_uses_the_same_public_named_multi_input_action(self):
        run_id, projection = self.execute_workflow(self.workflow())
        self.assertEqual(projection['status'], 'succeeded', projection)
        response = self.client.post(f'/api/v2/projects/{self.project}/runs/{run_id}/results:action', json={
            'action_id': 'result_action_fixture.read_counts', 'parameters': {}, 'inputs': {
                'subjects': [{'node_id': 'population', 'output_port': 'candidates', 'value_index': 0, 'slot': 'study'}],
                'measurements': [{'node_id': 'measurements', 'output_port': 'scores', 'value_index': 0, 'slot': 'observed'}]}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'subject_count': 3, 'measurement_count': 3})

    def test_ambiguous_observations_stop_both_public_adapters(self):
        workflow = self.workflow()
        self.add_comparisons(workflow)
        parameters = workflow['nodes'][2]['node_parameters']
        parameters['selection'] = self.comparison_selection()
        workflow['edges'][-1] = {'source_node_id': 'comparisons', 'source_port': 'scores',
            'target_node_id': 'chosen', 'target_port': 'scores', 'target_slot': 'comparisons'}
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'failed', projection)
        response = self.action(run_id, {'sort': {key: value for key, value in parameters.items() if key != 'k'}}, scores=[
            {'node_id': 'comparisons', 'output_port': 'scores', 'value_index': 0, 'slot': 'comparisons'}])
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn('needs exactly one selected evaluation; found 2', response.json()['error']['message'])
        self.assertEqual(self.node_failure_message(run_id, 'chosen'), response.json()['error']['message'])

    def test_exact_existing_reference_and_region_choices_match_the_node(self):
        workflow = self.workflow()
        self.add_comparisons(workflow)
        recorded_run, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        observations = self.client.post(f'/api/v2/projects/{self.project}/runs/{recorded_run}/results:value',
            json={'node_id': 'comparisons', 'output_port': 'scores', 'value_index': 0}).json()['value']['entries']
        subjects = list(dict.fromkeys(entry['subject']['candidate_id'] for entry in observations))
        choices = [next(entry for entry in observations if entry['subject']['candidate_id'] == subject
                        and entry['context']['subject_region'] == [region])
                   for subject, region in zip(subjects, ['A:1', 'A:9', 'A:1'])]
        selection = dict(self.comparison_selection(), exact_contexts=[
            {'subject': entry['subject'], 'context': entry['context'], 'residue_axis': entry['residue_axis']}
            for entry in choices])
        sorting = {'selection': selection, 'direction': 'descending'}
        workflow['nodes'][2].update(node_type_id='selection.sort', binding_id='selection.sort.direct', node_parameters=sorting)
        run_id, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        response = self.action(run_id, {'sort': sorting}, scores=[
            {'node_id': 'comparisons', 'output_port': 'scores', 'value_index': 0, 'slot': 'comparisons'}])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'candidate_indices': [1, 2, 0]})
        original = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/population/candidates/values/0').json()['value']['fields']['items']
        chosen = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0').json()['value']['fields']['items']
        self.assertEqual(chosen, [original[index] for index in response.json()['candidate_indices']])

    def comparison_selection(self):
        return {'score_input': 'comparisons', 'metric_id': 'result_action_fixture.measurement',
                'method_id': 'result_action_fixture.comparisons.method', 'source_partition': 'raw',
                'context': {'kind': 'pairwise', 'subject_role': 'subject', 'reference_role': 'reference',
                            'pairing_mode': 'fixed_reference', 'normalization': 'reference-length'}}

    def add_comparisons(self, workflow):
        def node(identity, kind, parameters=None):
            return {'node_id': identity, 'node_type_id': kind, 'binding_id': kind + '.direct',
                    'node_parameters': parameters or {}, 'binding_parameters': {}}
        workflow['nodes'].extend([node('reference-a', 'selection_fixture.backbone', {'index': 0}),
            node('reference-b', 'selection_fixture.backbone', {'index': 1}),
            node('comparisons-a', 'result_action_fixture.comparisons'),
            node('comparisons-b', 'result_action_fixture.comparisons', {'region': 'A:9', 'offset': 20}),
            node('comparisons', 'collection_ops.merge_scores')])
        workflow['edges'].extend([
            *[{'source_node_id': 'reference-' + suffix, 'source_port': 'candidates', 'target_node_id': 'comparisons-' + suffix, 'target_port': 'references'} for suffix in ('a', 'b')],
            *[{'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'comparisons-' + suffix, 'target_port': 'subjects'} for suffix in ('a', 'b')],
            *[{'source_node_id': 'comparisons-' + suffix, 'source_port': 'scores', 'target_node_id': 'comparisons', 'target_port': 'scores_' + suffix} for suffix in ('a', 'b')],
            {'source_node_id': 'comparisons', 'source_port': 'scores', 'target_node_id': 'chosen', 'target_port': 'scores', 'target_slot': 'comparisons'}])


if __name__ == '__main__':
    unittest.main()
