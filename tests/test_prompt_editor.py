"""Prompt editor discovery through the public module interface."""
import os
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
