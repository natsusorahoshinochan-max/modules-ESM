"""Prompt editor discovery through the public module interface."""
import os
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class PromptEditor(unittest.TestCase):
    def test_prompt_editor_is_available_through_module_interface(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': directory}):
                with TestClient(create_application()) as client:
                    response = client.get('/api/v2/module-ui')
                    self.assertEqual(response.status_code, 200, response.text)
                    editors = [editor for extension in response.json()['extensions']
                               for editor in extension['editors']
                               if 'prompt_authoring.author' in editor['node_type_ids']]
                    self.assertEqual(len(editors), 1)
                    self.assertEqual(editors[0]['title'], 'Prompt Studio')

    def test_prompt_open_reports_enabled_module_condition_projections(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': directory}):
                with TestClient(create_application()) as client:
                    project_id = client.post('/api/v2/projects', json={'name': 'Conditions'}).json()['id']
                    workflow = {'schema_version': '2.1.0', 'workflow_id': project_id, 'edges': [], 'nodes': [{
                        'node_id': 'prompt', 'node_type_id': 'prompt_authoring.author',
                        'binding_id': 'prompt_authoring.author.direct', 'binding_parameters': {},
                        'node_parameters': {'document': {'chains': [{'chain_id': 'A', 'length': 3}]}},
                    }]}
                    response = client.post(f'/api/v2/projects/{project_id}/authoring-actions/prompt_authoring.open', json={'parameters': {'node_id': 'prompt', 'workflow': workflow}})
                    self.assertEqual(response.status_code, 200, response.text)
                    projections = response.json()['tool_projections']
                    self.assertEqual([entry['projection_id'] for entry in projections], ['esm3.conditioning'])
                    self.assertEqual(projections[0]['value']['effective_input']['sequence'], '___')
                    inventory = client.get('/api/v2/modules').json()
                    enabled = [entry['package_id'] for entry in inventory['modules'] if entry['enabled'] and entry['package_id'] != 'esm3']
                    changed = client.put('/api/v2/modules', json={'enabled_package_ids': enabled})
                    self.assertEqual(changed.status_code, 200, changed.text)
                    response = client.post(f'/api/v2/projects/{project_id}/authoring-actions/prompt_authoring.open', json={'parameters': {'node_id': 'prompt', 'workflow': workflow}})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['tool_projections'], [])
                    self.assertEqual(len(response.json()['residues']), 3)

    def test_adopted_preview_is_saved_reopened_and_passed_to_generation(self):
        import time
        from esm.sdk.api import ESMProtein
        requests = []

        class SDK:
            def generate(self, protein, config):
                requests.append((protein.sequence, config.track, config.num_steps))
                return ESMProtein(sequence='WAS')

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': directory}):
                with TestClient(create_application()) as client:
                    project_id = client.post('/api/v2/projects', json={'name': 'Adopted prompt'}).json()['id']
                    base = f'/api/v2/projects/{project_id}'
                    workflow = {'schema_version': '2.1.0', 'workflow_id': project_id, 'nodes': [
                        {'node_id': 'prompt', 'node_type_id': 'prompt_authoring.author', 'binding_id': 'prompt_authoring.author.direct', 'binding_parameters': {}, 'node_parameters': {'document': {'chains': [{'chain_id': 'A', 'length': 3}]}}},
                        {'node_id': 'generate', 'node_type_id': 'esm3.generate_sequence', 'binding_id': 'esm3.generate_sequence.biohub_open', 'node_parameters': {'num_samples': 1}, 'binding_parameters': {'num_steps': 1}},
                    ], 'edges': [{'source_node_id': 'prompt', 'source_port': 'protein_prompt', 'target_node_id': 'generate', 'target_port': 'protein_prompt'}]}
                    document = {**workflow['nodes'][0]['node_parameters']['document'], 'track_edits': [{'track': 'sequence', 'action': 'replace', 'residue_id': 'A:1', 'value': 'W'}]}
                    preview = client.post(base + '/authoring-actions/prompt_authoring.preview', json={'parameters': {'node_id': 'prompt', 'workflow': workflow, 'document': document}})
                    self.assertEqual(preview.status_code, 200, preview.text)
                    self.assertEqual(preview.json()['diagnostics'], [])
                    workflow['nodes'][0]['node_parameters']['document'] = preview.json()['normalized_document']
                    saved = client.put(base + '/workspace', json={'workflow': workflow, 'ui_state': {}, 'expected_draft_revision': 0, 'expected_workspace_revision': 0})
                    self.assertEqual(saved.status_code, 200, saved.text)
                with TestClient(create_application()) as client:
                    reopened = client.get(base + '/workspace').json()['draft']['workflow']
                    self.assertEqual(reopened['nodes'], workflow['nodes'])
                    self.assertEqual(reopened['edges'], workflow['edges'])
                    setting = client.patch('/api/v2/module-settings/esm3.generate_sequence.biohub_open', json={'values': {'credential_handle': 'controlled-sdk-only'}})
                    self.assertEqual(setting.status_code, 200, setting.text)
                    commit = client.post(base + '/workflow:commit', json={'workflow': reopened})
                    self.assertEqual(commit.status_code, 200, commit.text)
                    with patch('esm.sdk.client', return_value=SDK()):
                        receipt = client.post(base + '/runs', json={'workflow_commit_id': commit.json()['workflow_commit_id'], 'client_request_id': 'adopted-prompt'})
                        self.assertEqual(receipt.status_code, 202, receipt.text)
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            run = client.get(base + '/runs/' + receipt.json()['run_id']).json()
                            if run['status'] not in ('admitted', 'running'):
                                break
                            time.sleep(.01)
                    self.assertEqual(run['status'], 'succeeded', run)
                    self.assertEqual(requests, [('W__', 'sequence', 1)])

class AppliedPromptOperations(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': self.directory.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(create_application())
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        project_id = self.client.post('/api/v2/projects', json={'name': 'Editing'}).json()['id']
        self.base = f'/api/v2/projects/{project_id}'
        self.workflow = {'schema_version': '2.1.0', 'workflow_id': project_id, 'edges': [], 'nodes': [{
            'node_id': 'prompt', 'node_type_id': 'prompt_authoring.author',
            'binding_id': 'prompt_authoring.author.direct', 'binding_parameters': {},
            'node_parameters': {'document': {'chains': [{'chain_id': 'A', 'length': 4}]}},
        }]}

    def preview(self, document):
        response = self.client.post(self.base + '/authoring-actions/prompt_authoring.preview', json={
            'parameters': {'node_id': 'prompt', 'workflow': self.workflow, 'document': document}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['diagnostics'], [])
        return response.json()

    def test_adopted_random_mask_is_fixed_when_a_selected_residue_is_deleted(self):
        document = {'chains': [{'chain_id': 'A', 'length': 4}],
                    'track_edits': [{'track': 'sequence', 'action': 'replace', 'residue_id': f'A:{i}', 'value': 'A'} for i in range(1, 5)],
                    'random_operations': [{'kind': 'mask', 'track': 'sequence', 'seed': 7, 'count': 3, 'eligible_residue_ids': ['A:1', 'A:2', 'A:3', 'A:4']}]}
        adopted = self.preview(document)
        masked = [r['residue_id'] for r, v in zip(adopted['residues'], adopted['tracks']['sequence']['values']) if v['value'] is None]
        next_document = deepcopy(adopted['normalized_document'])
        removed = masked[0]
        next_document['target_residues'] = [{'residue_id': f'A:{i}', 'origin': 'source'} for i in range(1, 5) if f'A:{i}' != removed]
        next_document['track_edits'] = [e for e in next_document['track_edits'] if e['residue_id'] != removed]
        result = self.preview(next_document)
        remaining = {r['residue_id'] for r, v in zip(result['residues'], result['tracks']['sequence']['values']) if v['value'] is None and r['state'] != 'pending-delete'}
        self.assertEqual(remaining, set(masked) - {removed})
        self.assertEqual(result['normalized_document']['applied_random_operations'][0]['operation']['seed'], 7)

    def test_adopted_transform_can_be_cleared_then_replaced_without_replaying(self):
        document = {'chains': [{'chain_id': 'A', 'length': 2}],
                    'track_edits': [{'track': 'coordinates', 'action': 'replace', 'residue_id': f'A:{i}', 'value': {'atom_coordinates': [{'atom_name': 'CA', 'coordinates': [i, 0, 0]}]}} for i in (1, 2)],
                    'rigid_transforms': [{'residue_ids': ['A:1', 'A:2'], 'rotation_matrix': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'origin': [0, 0, 0], 'translation': [10, 0, 0]}]}
        adopted = self.preview(document)
        next_document = deepcopy(adopted['normalized_document'])
        next_document['track_edits'] = [e for e in next_document['track_edits'] if e['residue_id'] != 'A:1'] + [{'track': 'coordinates', 'action': 'clear', 'residue_id': 'A:1'}]
        cleared = self.preview(next_document)
        values = cleared['tracks']['coordinates']['values']
        self.assertIsNone(values[0]['value'])
        self.assertEqual(values[1]['value']['atoms'][0]['coordinates'], [12, 0, 0])
        next_document['track_edits'][-1] = {'track': 'coordinates', 'action': 'replace', 'residue_id': 'A:1', 'value': {'atom_coordinates': [{'atom_name': 'CA', 'coordinates': [3, 0, 0]}]}}
        replaced = self.preview(next_document)
        self.assertEqual(replaced['tracks']['coordinates']['values'][0]['value']['atoms'][0]['coordinates'], [3, 0, 0])
        restored = self.preview(adopted['normalized_document'])
        self.assertEqual(restored['tracks']['coordinates']['values'][0]['value']['atoms'][0]['coordinates'], [11, 0, 0])

    def test_adopted_random_insertions_are_ordinary_residues_and_repeat_is_new(self):
        operation = {'kind': 'insert', 'seed': 7, 'count': 2}
        first = self.preview({'chains': [{'chain_id': 'A', 'length': 2}], 'random_operations': [operation]})
        document = first['normalized_document']
        self.assertEqual(document.get('random_operations'), [])
        inserted = [row['residue_id'] for row in document['target_residues'] if row['origin'] == 'inserted']
        self.assertEqual(len(inserted), 2)
        document['track_edits'] = [{'track': 'sequence', 'action': 'replace', 'residue_id': residue_id, 'value': 'W'} for residue_id in inserted]
        document['random_operations'] = [{'kind': 'mask', 'track': 'sequence', 'seed': 1, 'count': 2, 'eligible_residue_ids': inserted}]
        masked = self.preview(document)['normalized_document']
        masked['target_residues'] = [row for row in masked['target_residues'] if row['residue_id'] != inserted[0]]
        masked['track_edits'] = [row for row in masked['track_edits'] if row['residue_id'] != inserted[0]]
        deleted = self.preview(masked)
        self.assertEqual(len(deleted['residues']), 3)
        again = deleted['normalized_document']
        again['random_operations'] = [operation]
        repeated = self.preview(again)
        self.assertEqual(len(repeated['residues']), 5)
        self.assertIn(inserted[1], [row['residue_id'] for row in repeated['residues']])

    def test_random_insertion_keeps_complete_inherited_annotation_when_reopened(self):
        source = {'node_id': 'source', 'node_type_id': 'prompt_authoring.author', 'binding_id': 'prompt_authoring.author.direct', 'binding_parameters': {},
                  'node_parameters': {'document': {'chains': [{'chain_id': 'A', 'length': 3}], 'function_annotations': [{'label': 'binding', 'start_residue_id': 'A:1', 'end_residue_id': 'A:3'}]}}}
        self.workflow['nodes'].insert(0, source)
        self.workflow['nodes'][1]['node_parameters']['document'] = {}
        self.workflow['edges'] = [{'source_node_id': 'source', 'source_port': 'protein_prompt', 'target_node_id': 'prompt', 'target_port': 'prompt_source'}]
        first = self.preview({'random_operations': [{'kind': 'insert', 'seed': 1, 'count': 1}]})
        reopened = self.preview(first['normalized_document'])
        self.assertEqual(reopened['function_annotations'], first['function_annotations'])
        self.assertEqual(len(reopened['function_annotations']), 1)

    def test_open_materializes_saved_recipe_without_saving_or_changing_its_result(self):
        document = {'chains': [{'chain_id': 'A', 'length': 2}],
                    'track_edits': [{'track': 'coordinates', 'action': 'replace', 'residue_id': 'A:1', 'value': {'atom_coordinates': [{'atom_name': 'CA', 'coordinates': [1, 0, 0]}]}}],
                    'rigid_transforms': [{'residue_ids': ['A:1'], 'rotation_matrix': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'origin': [0, 0, 0], 'translation': [10, 0, 0]}],
                    'random_operations': [{'kind': 'insert', 'seed': 1, 'count': 1}]}
        self.workflow['nodes'][0]['node_parameters']['document'] = document
        saved = self.client.put(self.base + '/workspace', json={'workflow': self.workflow, 'ui_state': {}, 'expected_draft_revision': 0, 'expected_workspace_revision': 0})
        self.assertEqual(saved.status_code, 200, saved.text)
        opened = self.client.post(self.base + '/authoring-actions/prompt_authoring.open', json={'parameters': {'node_id': 'prompt'}})
        self.assertEqual(opened.status_code, 200, opened.text)
        current = self.client.get(self.base + '/workspace').json()
        self.assertEqual(current['draft']['workflow']['nodes'][0]['node_parameters']['document'], document)
        replayed = self.preview(opened.json()['document'])
        self.assertEqual(replayed['tracks']['coordinates']['values'], opened.json()['tracks']['coordinates']['values'])
        self.assertEqual(replayed['normalized_document']['random_operations'], [])

    def test_random_insert_after_adopted_merge_uses_current_complete_layout(self):
        source = {'node_id': 'source', 'node_type_id': 'prompt_authoring.author', 'binding_id': 'prompt_authoring.author.direct', 'binding_parameters': {},
                  'node_parameters': {'document': {'chains': [{'chain_id': 'B', 'length': 1}], 'track_edits': [{'track': 'sequence', 'action': 'replace', 'residue_id': 'B:1', 'value': 'W'}]}}}
        self.workflow['nodes'].insert(0, source)
        self.workflow['edges'] = [{'source_node_id': 'source', 'source_port': 'protein_prompt', 'target_node_id': 'prompt', 'target_port': 'merge_sources'}]
        merged = self.preview({'chains': [{'chain_id': 'A', 'length': 1}], 'source_merges': [{'source_index': 0,
            'correspondence': [{'disposition': 'target_gap', 'target_residue_id': 'A:1'}, {'disposition': 'insert', 'source_residue_id': 'B:1', 'target_residue_id': 'A:merged'}],
            'track_adoptions': [{'track': 'sequence', 'source_residue_ids': ['B:1'], 'mask_policy': 'preserve'}], 'adopt_annotations': [], 'remove_annotations': []}]})
        document = merged['normalized_document']
        document['random_operations'] = [{'kind': 'insert', 'seed': 7, 'count': 1}]
        inserted = self.preview(document)
        reopened = self.preview(inserted['normalized_document'])
        self.assertEqual(len(reopened['residues']), 3)
        values = {row['residue_id']: value['value'] for row, value in zip(reopened['residues'], reopened['tracks']['sequence']['values'])}
        self.assertEqual(values['A:merged'], 'W')
        self.assertEqual(reopened['tracks'], inserted['tracks'])
        self.workflow['nodes'][1]['node_parameters']['document'] = reopened['normalized_document']
        commit = self.client.post(self.base + '/workflow:commit', json={'workflow': self.workflow})
        self.assertEqual(commit.status_code, 200, commit.text)
        receipt = self.client.post(self.base + '/runs', json={'workflow_commit_id': commit.json()['workflow_commit_id'], 'client_request_id': 'merged-random-prompt'})
        self.assertEqual(receipt.status_code, 202, receipt.text)
        import time
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            run = self.client.get(self.base + '/runs/' + receipt.json()['run_id']).json()
            if run['status'] not in ('admitted', 'running'):
                break
            time.sleep(.01)
        self.assertEqual(run['status'], 'succeeded', run)
