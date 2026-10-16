"""Node and readonly Selection preserve original exact historical Contexts."""
from dataclasses import replace
import unittest

from core.catalog.declarations import ScientificOperationFactory
from core.catalog.port_contract import BehaviorReference
from datatypes.exact_reference import ExactContractReference as Ref
from datatypes.observation import ScoreCollection
from modules.selection.tests import test_authoring_actions as authoring
from tests import test_selection_application as study
from tests.result_action_fixture import MODULE_PACKAGE as COMPARISONS, ExistingComparisons


class OriginalComparisons:
    def execute(self, call):
        scores = ExistingComparisons().execute(call)['scores']
        evidence = 'a' if call.node_parameters['region'] == 'A:1' else 'b'
        return {'scores': ScoreCollection(scores.collection_id, tuple(replace(score, context=replace(score.context,
            subject_region=None, reference_region=None, evidence_content_digest='sha256:' + evidence * 64,
            evidence_method=Ref('method', 'result_action_fixture.comparisons.method'),
            subject_axis_content_digest='sha256:' + 'c' * 64, reference_axis_content_digest='sha256:' + 'd' * 64,
            normalization_length=9, aligned_atom_count=1)) for score in scores))}


def original_registration():
    binding = COMPARISONS.bindings[0]
    return replace(COMPARISONS, bindings=(replace(binding, factory=ScientificOperationFactory(
        BehaviorReference('original-comparisons/factory'), lambda context: OriginalComparisons())),))


class ExactHistoricalContextTests(unittest.TestCase):
    extra_registrations = (original_registration(),)
    setUp = authoring.SelectionAuthoringTests.setUp
    execute_workflow = authoring.SelectionAuthoringTests.execute_workflow
    node = staticmethod(authoring.SelectionAuthoringTests.node)

    def test_readonly_and_normal_sort_use_unchanged_original_contexts_without_region_fields(self):
        workflow = study.SelectionApplicationTests.workflow(self)
        workflow['nodes'].extend([self.node('reference', 'selection_fixture.backbone', {'index': 0}),
            self.node('comparisons-a', 'result_action_fixture.comparisons'),
            self.node('comparisons-b', 'result_action_fixture.comparisons', {'region': 'A:9', 'offset': 20}),
            self.node('comparisons', 'collection_ops.merge_scores')])
        for suffix in ('a', 'b'):
            workflow['edges'].extend([
                {'source_node_id': 'reference', 'source_port': 'candidates', 'target_node_id': 'comparisons-' + suffix, 'target_port': 'references'},
                {'source_node_id': 'population', 'source_port': 'candidates', 'target_node_id': 'comparisons-' + suffix, 'target_port': 'subjects'},
                {'source_node_id': 'comparisons-' + suffix, 'source_port': 'scores', 'target_node_id': 'comparisons', 'target_port': 'scores_' + suffix}])
        original_run, projection = self.execute_workflow(workflow)
        self.assertEqual(projection['status'], 'succeeded', projection)
        original_path = f'/api/v2/projects/{self.project}/runs/{original_run}/outputs/comparisons/scores/values/0'
        original_bytes = self.client.get(original_path).content
        observations = self.client.post(f'/api/v2/projects/{self.project}/runs/{original_run}/results:value',
            json={'node_id': 'comparisons', 'output_port': 'scores', 'value_index': 0}).json()['value']['entries']
        self.assertTrue(all('subject_region' not in entry['context'] and 'reference_region' not in entry['context'] for entry in observations))
        subjects = list(dict.fromkeys(entry['subject']['candidate_id'] for entry in observations))
        choices = [next(entry for entry in observations if entry['subject']['candidate_id'] == subject
            and entry['context']['evidence_content_digest'] == 'sha256:' + evidence * 64)
            for subject, evidence in zip(subjects, ['a', 'b', 'a'])]
        selection = {'score_input': 'comparisons', 'metric_id': 'result_action_fixture.measurement',
            'method_id': 'result_action_fixture.comparisons.method', 'source_partition': 'raw',
            'context': {'kind': 'pairwise', 'subject_role': 'subject', 'reference_role': 'reference',
                'pairing_mode': 'fixed_reference', 'normalization': 'reference-length'},
            'exact_contexts': [{'subject': entry['subject'], 'context': entry['context'], 'residue_axis': entry['residue_axis']} for entry in choices]}
        sorting = {'selection': selection, 'direction': 'descending'}
        workflow['nodes'][2].update(node_type_id='selection.sort', binding_id='selection.sort.direct', node_parameters=sorting)
        workflow['edges'][2] = {'source_node_id': 'comparisons', 'source_port': 'scores',
            'target_node_id': 'chosen', 'target_port': 'scores', 'target_slot': 'comparisons'}
        saved = self.client.put(f'/api/v2/projects/{self.project}/workspace', json={'workflow': workflow, 'ui_state': {}})
        self.assertEqual(saved.status_code, 200, saved.text)
        reopened = self.client.get(f'/api/v2/projects/{self.project}/workspace').json()['draft']['workflow']
        self.assertEqual(reopened['nodes'][2]['node_parameters']['selection']['exact_contexts'], selection['exact_contexts'])
        run_id, projection = self.execute_workflow(reopened)
        self.assertEqual(projection['status'], 'succeeded', projection)
        readonly = self.client.post(f'/api/v2/projects/{self.project}/runs/{original_run}/results:action', json={
            'action_id': 'selection.view', 'parameters': {'sort': sorting}, 'inputs': {
                'candidates': [{'node_id': 'population', 'output_port': 'candidates', 'value_index': 0, 'slot': 'population'}],
                'scores': [{'node_id': 'comparisons', 'output_port': 'scores', 'value_index': 0, 'slot': 'comparisons'}]}})
        self.assertEqual(readonly.status_code, 200, readonly.text)
        self.assertEqual(readonly.json(), {'candidate_indices': [1, 2, 0]})
        original = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/population/candidates/values/0').json()['value']['fields']['items']
        chosen = self.client.get(f'/api/v2/projects/{self.project}/runs/{run_id}/outputs/chosen/candidates/values/0').json()['value']['fields']['items']
        self.assertEqual(chosen, [original[1], original[2], original[0]])
        self.assertEqual(self.client.get(original_path).content, original_bytes)

    def test_unfinished_pairwise_editor_can_offer_measurements_before_reference_context_is_chosen(self):
        response = self.client.post(f'/api/v2/projects/{self.project}/authoring-actions/selection.observation_options', json={
            'parameters': {'workflow': {'nodes': [self.node('comparison', 'result_action_fixture.comparisons')], 'edges': []}, 'ranking': True}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'options': [{'source': {'node_id': 'comparison', 'output_port': 'scores'},
            'partition': 'raw', 'metric_id': 'result_action_fixture.measurement',
            'method_id': 'result_action_fixture.comparisons.method', 'context': {'kind': 'pairwise',
                'subject_role': 'subject', 'reference_role': 'reference', 'pairing_mode': 'fixed_reference', 'normalization': 'reference-length'}}]})
