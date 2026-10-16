"""Module-owned unpublished input reading and editing through public HTTP."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class AuthoringActions(unittest.TestCase):
    def test_external_inspection_and_preview_use_staged_input_without_saving(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            Path(root, 'modules.json').write_text(json.dumps({'packages': [{
                'package_id': 'authoring_demo', 'package_module': 'authoring_module',
                'enabled': True, 'source_root': str(Path(__file__).parent.resolve()),
            }]}))
            with TestClient(create_application(load_example_results=False)) as client:
                project = client.post('/api/v2/projects', json={'name': 'Draft reading'}).json()['id']
                base = f'/api/v2/projects/{project}'
                staged = {'project_input_ref': 'temperature', 'filename': 'reading.txt',
                          'content_base64': base64.b64encode(b'23.5').decode()}
                before = client.get(base + '/workspace').json()
                for action, payload, expected in (
                    ('inspect', {'project_input_ref': 'temperature'}, {'filename': 'reading.txt', 'reading': 23.5}),
                    ('preview', {'project_input_ref': 'temperature', 'offset': 2}, {'reading': 25.5, 'adopted': False}),
                ):
                    response = client.post(base + f'/authoring-actions/authoring_demo.{action}',
                                           json={'parameters': payload, 'prospective_inputs': [staged]})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json(), expected)
                self.assertEqual(client.get(base + '/workspace').json(), before)
                self.assertEqual(client.get(base + '/inputs').json()['inputs'], [])
                manifest = client.get('/api/v2/module-ui').json()
                self.assertEqual(manifest['authoring_actions'], ['authoring_demo.inspect', 'authoring_demo.preview'])
                disabled = client.put('/api/v2/modules', json={'enabled_package_ids': []})
                self.assertEqual(disabled.status_code, 200, disabled.text)
                self.assertEqual(client.get('/api/v2/module-ui').json()['authoring_actions'], [])
                for action in ('inspect', 'preview'):
                    response = client.post(base + f'/authoring-actions/authoring_demo.{action}',
                                           json={'parameters': {'project_input_ref': 'temperature'}, 'prospective_inputs': [staged]})
                    self.assertEqual(response.status_code, 404, response.text)

    def test_official_actions_share_registration_and_disable_with_the_module(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            with TestClient(create_application(load_example_results=False)) as client:
                project = client.post('/api/v2/projects', json={'name': 'Official preview'}).json()['id']
                base = f'/api/v2/projects/{project}'
                staged = {'project_input_ref': 'sequence', 'filename': 'sequence.fa',
                          'content_base64': base64.b64encode(b'>example\nACD\n').decode()}
                response = client.post(base + '/authoring-actions/protein_io.inspect_input', json={
                    'parameters': {'project_input_ref': 'sequence', 'format': 'fasta'}, 'prospective_inputs': [staged]})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['records'][0]['length'], 3)
                workflow = {'schema_version': '2.1.0', 'workflow_id': project, 'edges': [], 'nodes': [{
                    'node_id': 'prompt', 'node_type_id': 'prompt_authoring.author',
                    'binding_id': 'prompt_authoring.author.direct', 'binding_parameters': {},
                    'node_parameters': {'document': {'chains': [{'chain_id': 'A', 'length': 3}]}},
                }]}
                response = client.post(base + '/authoring-actions/prompt_authoring.open', json={
                    'parameters': {'node_id': 'prompt', 'workflow': workflow}})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(len(response.json()['residues']), 3)
                invalid = client.post(base + '/authoring-actions/prompt_authoring.preview', json={
                    'parameters': {'node_id': 'prompt', 'workflow': workflow, 'document': {'unknown_edit': True}}})
                self.assertEqual(invalid.status_code, 400, invalid.text)
                self.assertEqual(invalid.json()['error']['code'], 'malformed_request')
                missing = client.post(base + '/authoring-actions/protein_io.inspect_input', json={
                    'parameters': {'project_input_ref': 'missing', 'format': 'fasta'}})
                self.assertEqual(missing.status_code, 404, missing.text)
                bad_fasta = {**staged, 'content_base64': base64.b64encode(b'>empty\n').decode()}
                invalid = client.post(base + '/authoring-actions/protein_io.inspect_input', json={
                    'parameters': {'project_input_ref': 'sequence', 'format': 'fasta'}, 'prospective_inputs': [bad_fasta]})
                self.assertEqual(invalid.status_code, 422, invalid.text)
                disabled = client.put('/api/v2/modules', json={'enabled_package_ids': []})
                self.assertEqual(disabled.status_code, 200, disabled.text)
                for action in ('protein_io.inspect_input', 'prompt_authoring.open', 'prompt_authoring.preview'):
                    response = client.post(base + '/authoring-actions/' + action, json={'parameters': {}})
                    self.assertEqual(response.status_code, 404, response.text)
