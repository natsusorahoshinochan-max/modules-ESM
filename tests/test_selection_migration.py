"""One-time saved Selection conversion through current public operations."""

from copy import deepcopy
import unittest

from modules.selection.migration import convert_selection_workflow
from tests import test_selection_application as study


def saved_selection(operation):
    """A saved user configuration, built independently of removed parsers."""
    objectives = [{
        'objective_id': 'confidence',
        'candidate_input': {'node_id': 'population', 'output_port': 'candidates'},
        'score_collection_input': {'node_id': 'measurements', 'output_port': 'scores'},
        'metric': {'contract_kind': 'metric', 'contract_id': 'structure.plddt.mean_residue'},
        'method': {'contract_kind': 'method', 'contract_id': 'old.predict'},
        'context_selector': {'kind': 'intrinsic'}, 'source_partition': 'confidence',
        'utility_transform': {'contract_kind': 'utility_transform', 'contract_id': 'old.percent_to_unit'},
        'utility_parameters': {}, 'weight': 1, 'match_cardinality': 'exactly_one',
        'missing_policy': 'error',
    }]
    parameters = ({'objective_id': 'confidence', 'out_of_scope_policy': 'ignore'}
                  if operation in ('sort', 'top_k') else {'objective_ids': ['confidence']})
    if operation in ('top_k', 'diversity'):
        parameters['k'] = 3
    return {'schema_version': '2.1.0', 'workflow_id': 'saved-study', 'nodes': [{
        'node_id': 'chosen', 'node_type_id': 'selection.' + operation,
        'binding_id': 'selection.' + operation + '.direct',
        'node_parameters': parameters, 'binding_parameters': {},
    }], 'edges': [
        {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'chosen', 'target_port': 'candidates'},
        {'source_node_id': 'measurements', 'source_port': 'scores', 'target_node_id': 'chosen', 'target_port': 'scores'},
    ], 'selection_objectives': objectives, 'observation_selectors': []}


class SelectionMigrationTests(unittest.TestCase):
    def test_saved_rankings_and_removed_diversity_retain_exact_settings_and_connections(self):
        for operation in ('sort', 'top_k', 'weighted_rank', 'pareto', 'diversity'):
            with self.subTest(operation=operation):
                workflow = saved_selection(operation)
                original = deepcopy(workflow)

                converted = convert_selection_workflow(workflow)

                self.assertEqual(workflow, original)
                self.assertNotIn('selection_objectives', converted)
                self.assertNotIn('observation_selectors', converted)
                self.assertEqual(converted['edges'], original['edges'])
                retained = converted['nodes'][0]
                self.assertEqual({key: value for key, value in retained.items()
                                  if key != 'preserved_configuration'}, original['nodes'][0])
                self.assertTrue(retained['preserved_configuration']['reason'])
                self.assertEqual(retained['preserved_configuration']['settings'], {
                    'selection_objectives': original['selection_objectives'], 'observation_selectors': []})
                self.assertEqual(retained['preserved_configuration']['project_input_parameters'], [])

    def test_legacy_filter_keeps_all_selectors_and_postfix_conditions_when_equivalence_is_unproven(self):
        workflow = saved_selection('sort')
        objective = workflow['selection_objectives'][0]
        selector = {key: deepcopy(value) for key, value in objective.items()
                    if key not in ('objective_id', 'utility_transform', 'utility_parameters', 'weight')}
        selector['selector_id'] = 'confidence'
        workflow['selection_objectives'] = []
        workflow['observation_selectors'] = [selector]
        workflow['nodes'][0].update(node_type_id='selection.filter', binding_id='selection.filter.direct',
            node_parameters={'selector_ids': ['confidence'], 'expression': [
                {'selector_index': 0, 'operator': '>=', 'threshold': 80}], 'out_of_scope_policy': 'ignore'})
        workflow['edges'][-1]['target_slot'] = 'confidence-values'
        original = deepcopy(workflow)

        converted = convert_selection_workflow(workflow)

        retained = converted['nodes'][0]
        self.assertEqual(retained['node_parameters'], original['nodes'][0]['node_parameters'])
        self.assertEqual(converted['edges'], original['edges'])
        self.assertEqual(retained['preserved_configuration']['settings']['observation_selectors'], [selector])
        self.assertIn('matching', retained['preserved_configuration']['reason'])

    def test_unconsumed_global_settings_survive_without_changing_existing_nodes_or_edges(self):
        workflow = saved_selection('sort')
        workflow['nodes'] = [{
            'node_id': 'retained-selection-configuration', 'node_type_id': 'selection.manual',
            'binding_id': 'selection.manual.direct', 'node_parameters': {'selected_candidates': []},
            'binding_parameters': {},
        }]
        workflow['edges'] = []
        original = deepcopy(workflow)

        converted = convert_selection_workflow(workflow)

        self.assertEqual(converted['nodes'][:1], original['nodes'])
        self.assertEqual(converted['edges'], [])
        retained = converted['nodes'][1]
        self.assertNotEqual(retained['node_id'], 'retained-selection-configuration')
        self.assertEqual(retained['node_type_id'], 'selection.unavailable_configuration')
        self.assertEqual(retained['preserved_configuration']['settings'], {
            'observation_selectors': [], 'selection_objectives': original['selection_objectives']})
        self.assertEqual(convert_selection_workflow(converted), converted)


class SelectionMigrationApplicationTests(unittest.TestCase):
    setUp = study.SelectionApplicationTests.setUp
    tearDown = study.SelectionApplicationTests.tearDown
    execute_workflow = study.SelectionApplicationTests.execute_workflow

    def test_current_node_owned_rules_still_save_reopen_and_run_after_conversion(self):
        workflow = study.SelectionApplicationTests.workflow(self)
        original = deepcopy(workflow)
        workflow['observation_selectors'] = []
        workflow['selection_objectives'] = []

        converted = convert_selection_workflow(workflow)

        self.assertEqual(converted, original)
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace',
            json={'workflow': converted, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = self.client.get(f'/api/v2/projects/{self.project}/workspace').json()['draft']['workflow']
        self.assertEqual(reopened['nodes'][-1], original['nodes'][-1])
        _, result = self.execute_workflow(reopened)
        self.assertEqual(result['status'], 'succeeded', result)

    def test_saved_sort_settings_are_readable_after_reopen_and_cannot_run_under_new_defaults(self):
        workflow = study.SelectionApplicationTests.workflow(self)
        legacy = saved_selection('sort')
        legacy['nodes'][0]['node_id'] = 'chosen'
        workflow['nodes'][-1] = legacy['nodes'][0]
        workflow['selection_objectives'] = legacy['selection_objectives']
        workflow['observation_selectors'] = []

        converted = convert_selection_workflow(workflow)
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace',
            json={'workflow': converted, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = self.client.get(f'/api/v2/projects/{self.project}/workspace').json()['draft']['workflow']
        self.assertEqual(reopened['nodes'][-1], converted['nodes'][-1])
        self.assertEqual(reopened['edges'], workflow['edges'])
        committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit',
            json={'workflow': reopened})
        self.assertEqual(committed.status_code, 422, committed.text)
        self.assertIn('preserved_configuration_unavailable', committed.text)

    def test_saved_manual_selection_keeps_its_existing_empty_choice_and_runs(self):
        workflow = study.SelectionApplicationTests.workflow(self)
        workflow['nodes'][-1].update(node_type_id='selection.manual', binding_id='selection.manual.direct',
            node_parameters={'selected_candidates': []})
        workflow['edges'] = [edge for edge in workflow['edges']
                             if not (edge['target_node_id'] == 'chosen' and edge['target_port'] == 'scores')]
        original = deepcopy(workflow)

        converted = convert_selection_workflow(workflow)

        self.assertEqual(converted, original)
        run_id, result = self.execute_workflow(converted)
        self.assertEqual(result['status'], 'succeeded', result)
        output = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0')
        self.assertEqual(output.status_code, 200, output.text)
        self.assertEqual(output.json()['value']['fields']['items'], [])


if __name__ == '__main__':
    unittest.main()
