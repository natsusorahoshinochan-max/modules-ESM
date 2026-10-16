"""Node-local grouped filtering through public project and run operations."""
import unittest
from dataclasses import replace

from core.catalog.builtins import builtin_port_types
from datatypes.candidate import Candidate, CandidateCollection, CandidateDataReference
from datatypes.exact_reference import ExactContractReference
from datatypes.observation import PairwiseObservationContext, PairwiseParticipant, ScoreCollection, ScoreObservation
from datatypes.sequence import ProteinSequence
from modules.selection.compute import SelectionError, select_candidates
from modules.selection.published_reading import read_scores

from tests import test_selection_application as study


class ConditionApplicationTests(unittest.TestCase):
    # Share only the temporary public application and scientific input fixture.
    setUp = study.SelectionApplicationTests.setUp
    tearDown = study.SelectionApplicationTests.tearDown
    execute_workflow = study.SelectionApplicationTests.execute_workflow

    def workflow(self):
        workflow = study.SelectionApplicationTests.workflow(self)
        selected = workflow['nodes'][-1]
        selection = selected['node_parameters']['selection']
        selected.update(node_type_id='selection.filter', binding_id='selection.filter.direct', node_parameters={
            'condition': {'kind': 'comparison', 'selection': selection, 'operator': '>=', 'threshold': 10}})
        return workflow

    def test_disconnected_score_in_nested_condition_cannot_silently_choose_another_input(self):
        workflow = self.workflow()
        comparison = workflow['nodes'][2]['node_parameters']['condition']
        disconnected = dict(comparison, selection=dict(comparison['selection'], score_input='old-source'))
        workflow['nodes'][2]['node_parameters']['condition'] = {
            'kind': 'group', 'operator': 'or', 'children': [comparison,
                {'kind': 'group', 'operator': 'and', 'children': [disconnected]}]}
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
        self.assertEqual(committed.status_code, 422, committed.text)
        self.assertIn('old-source', committed.text)

    def test_unfinished_or_invalid_condition_is_saved_but_not_runnable(self):
        for condition in [
            {'kind': 'group', 'operator': 'and', 'children': []},
            {'kind': 'comparison', 'selection': {}, 'operator': '>=', 'threshold': 0},
            {'kind': 'comparison', 'selection': self.workflow()['nodes'][2]['node_parameters']['condition']['selection'],
             'operator': 'approximately', 'threshold': 0},
        ]:
            with self.subTest(condition=condition):
                workflow = self.workflow()
                workflow['nodes'][2]['node_parameters']['condition'] = condition
                saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
                self.assertEqual(saved.status_code, 200, saved.text)
                committed = self.client.post(f'/api/v2/projects/{self.project}/workflow:commit', json={'workflow': workflow})
                self.assertEqual(committed.status_code, 422, committed.text)

    def test_boolean_shortcuts_cannot_hide_missing_scores_and_independent_branch_finishes(self):
        for operator, first_threshold in [('or', -100), ('and', 100)]:
            with self.subTest(operator=operator):
                workflow = self.workflow()
                first = workflow['nodes'][2]['node_parameters']['condition']
                second = dict(first, selection=dict(first['selection'], score_input='missing-scores'))
                workflow['nodes'][2]['node_parameters']['condition'] = {
                    'kind': 'group', 'operator': operator,
                    'children': [dict(first, threshold=first_threshold), second]}
                workflow['nodes'].extend([
                    dict(workflow['nodes'][1], node_id='incomplete', node_parameters={'values': [12, None, -8]}),
                    dict(workflow['nodes'][1], node_id='dependent', node_parameters={}),
                    dict(workflow['nodes'][1], node_id='independent', node_parameters={})])
                workflow['edges'].extend([
                    {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'incomplete', 'target_port': 'candidates'},
                    {'source_node_id': 'incomplete', 'source_port': 'scores', 'target_node_id': 'chosen', 'target_port': 'scores', 'target_slot': 'missing-scores'},
                    {'source_node_id': 'chosen', 'source_port': 'candidates', 'target_node_id': 'dependent', 'target_port': 'candidates'},
                    {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'independent', 'target_port': 'candidates'}])
                _, result = self.execute_workflow(workflow)
                dispositions = {item['node_id']: item['outcome'] for item in result['node_dispositions']}
                self.assertEqual(dispositions['chosen'], 'failed', result)
                self.assertEqual(dispositions['dependent'], 'blocked', result)
                self.assertEqual(dispositions['independent'], 'succeeded', result)

    def test_grouped_conditions_keep_explicit_boolean_structure(self):
        workflow = self.workflow()
        leaf = workflow['nodes'][2]['node_parameters']['condition']
        workflow['nodes'][2]['node_parameters']['condition'] = {
            'kind': 'group', 'operator': 'or', 'children': [
                {'kind': 'group', 'operator': 'and', 'children': [
                    dict(leaf, operator='>', threshold=0), dict(leaf, operator='<', threshold=12)]},
                dict(leaf, operator='==', threshold=-8)]}
        run_id, result = self.execute_workflow(workflow)
        self.assertEqual(result['status'], 'succeeded', result)
        chosen = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0').json()
        names = [dict(item['fields']['metadata']['$map'])['display_name'] for item in chosen['value']['fields']['items']]
        self.assertEqual(names, ['last'])

    def test_saved_condition_reopens_runs_and_preserves_original_candidates_for_downstream(self):
        workflow = self.workflow()
        workflow['nodes'].append(dict(workflow['nodes'][1], node_id='downstream', node_parameters={}))
        workflow['edges'].append({'source_node_id': 'chosen', 'source_port': 'candidates',
                                 'target_node_id': 'downstream', 'target_port': 'candidates'})
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = self.client.get(f'/api/v2/projects/{self.project}/workspace').json()['draft']['workflow']
        self.assertEqual(reopened['nodes'][2]['node_parameters'], workflow['nodes'][2]['node_parameters'])
        run_id, result = self.execute_workflow(reopened)
        self.assertEqual(result['status'], 'succeeded', result)
        original = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/population/candidates/values/0').json()
        chosen = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0').json()
        downstream = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/downstream/scores/values/0')
        self.assertEqual(chosen['value']['fields']['items'], original['value']['fields']['items'][:2])
        self.assertEqual(downstream.status_code, 200, downstream.text)


class ConditionMatchingTests(unittest.TestCase):
    def test_exact_reference_and_region_choices_ignore_unselected_evaluations_and_keep_provenance(self):
        candidates = CandidateCollection('study', 'protein.sequence', (
            Candidate('one', ProteinSequence('AA'), ('real-parent',), {'source': 'experiment-one'}),
            Candidate('two', ProteinSequence('AC'), ('another-parent',), {'source': 'experiment-two'})))
        subjects = tuple(CandidateDataReference(item.candidate_id, 'protein.sequence', 'sha256:' + char * 64)
                         for item, char in zip(candidates, '12'))
        references = tuple(CandidateDataReference('reference-' + char, 'protein.structure', 'sha256:' + char * 64)
                           for char in '34')
        measurements = []
        for index, subject in enumerate(subjects):
            for reference, region, value in [(references[index], 'A:1', (2, 8)[index]),
                                             (references[1-index], 'A:9', (80, 1)[index])]:
                context = PairwiseObservationContext(PairwiseParticipant('subject', subject),
                    PairwiseParticipant('reference', reference), 'explicit_relation', 'reference-length',
                    subject_region=(region,), reference_region=('B:5',))
                measurements.append(ScoreObservation(subject, ExactContractReference('metric', 'test.raw'),
                    ExactContractReference('method', 'test.measure'), context, 'raw', value))
        # An unchosen method with a missing value must not become a requirement.
        measurements.append(replace(measurements[0], method=ExactContractReference('method', 'test.unselected'), value=None))
        scores = ScoreCollection('measurements', tuple(measurements))
        port = next(port for port in builtin_port_types() if port.type_id == 'score.collection')
        reading = read_scores(port.encode(scores))['entries']
        selected = [reading[0], reading[2]]
        selection = {'score_input': 'measurements', 'metric_id': 'test.raw', 'method_id': 'test.measure',
                     'source_partition': 'raw', 'context': selected[0]['context_profile'],
                     'exact_contexts': [{'subject': item['subject'], 'context': item['context']} for item in selected]}
        result = select_candidates(candidates, subjects, {'measurements': (scores,)}, {
            'condition': {'kind': 'comparison', 'selection': selection, 'operator': '>=', 'threshold': 5}}, operation='filter')
        self.assertEqual(list(result), [candidates.items[1]])
        self.assertIs(result.items[0], candidates.items[1])

    def test_an_ambiguous_required_evaluation_stops_even_when_an_or_branch_is_true(self):
        candidate = Candidate('one', ProteinSequence('AA'))
        subject = CandidateDataReference('one', 'protein.sequence', 'sha256:' + '1' * 64)
        reference = CandidateDataReference('reference', 'protein.structure', 'sha256:' + '2' * 64)
        context = PairwiseObservationContext(PairwiseParticipant('subject', subject),
            PairwiseParticipant('reference', reference), 'explicit_relation', 'reference-length',
            subject_region=('A:1',), reference_region=('B:5',))
        first = ScoreObservation(subject, ExactContractReference('metric', 'test.raw'),
            ExactContractReference('method', 'test.measure'), context, 'raw', 8)
        second = replace(first, context=replace(context, subject_region=('A:9',)), value=2)
        scores = ScoreCollection('measurements', (first, second))
        port = next(port for port in builtin_port_types() if port.type_id == 'score.collection')
        reading = read_scores(port.encode(scores))['entries'][0]
        selection = {'score_input': 'measurements', 'metric_id': 'test.raw', 'method_id': 'test.measure',
                     'source_partition': 'raw', 'context': reading['context_profile']}
        exact = dict(selection, exact_contexts=[{'subject': reading['subject'], 'context': reading['context']}])
        with self.assertRaises(SelectionError) as caught:
            select_candidates(CandidateCollection('study', 'protein.sequence', (candidate,)), (subject,),
                {'measurements': (scores,)}, {'condition': {'kind': 'group', 'operator': 'or', 'children': [
                    {'kind': 'comparison', 'selection': exact, 'operator': '>=', 'threshold': 0},
                    {'kind': 'comparison', 'selection': selection, 'operator': '>=', 'threshold': 0}]}}, operation='filter')
        self.assertEqual(caught.exception.code, 'ambiguous_score')


if __name__ == '__main__':
    unittest.main()
