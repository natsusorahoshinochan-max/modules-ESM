"""Installed wheel lifecycle through public HTTP, including application reopen."""
import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class ModuleLifecycle(unittest.TestCase):
    def request(self, client, method, url, **kwargs):
        response = client.request(method, url, **kwargs)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def run_value(self, client, base, workflow, request_id):
        commit = self.request(client, 'POST', base + '/workflow:commit', json={'workflow': workflow})
        run = self.request(client, 'POST', base + '/runs', json={
            'workflow_commit_id': commit['workflow_commit_id'], 'client_request_id': request_id})
        run_url = base + '/runs/' + run['run_id']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.request(client, 'GET', run_url)
            if state['status'] not in ('admitted', 'running'):
                break
            time.sleep(.01)
        self.assertEqual(state['status'], 'succeeded', state)
        output_url = run_url + '/outputs/second/reading/values/0'
        return output_url, self.request(client, 'GET', output_url)

    def test_disabled_and_uninstalled_wheel_preserves_connected_work_after_reopen(self):
        wheel = Path(os.environ['WORKBENCH_MODULE_WHEEL'])
        install = {'filename': wheel.name, 'content_base64': base64.b64encode(wheel.read_bytes()).decode()}
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': root}):
            Path(root, 'modules.json').write_text(json.dumps({'packages': []}))
            with TestClient(create_application(load_example_results=False)) as client:
                self.request(client, 'POST', '/api/v2/modules/install', json=install)
                project = self.request(client, 'POST', '/api/v2/projects', json={'name': 'Connected external measurements'})
                base = '/api/v2/projects/' + project['id']
                workflow = {'schema_version': '2.1.0', 'workflow_id': project['id'], 'nodes': [
                    {'node_id': name, 'node_type_id': 'lifecycle_meter.add', 'binding_id': 'lifecycle_meter.add.direct',
                     'node_parameters': {'amount': amount, 'note': name}, 'binding_parameters': {}}
                    for name, amount in [('first', 7), ('second', 11)]
                ], 'edges': [{'source_node_id': 'first', 'source_port': 'reading', 'target_node_id': 'second', 'target_port': 'reading'}]}
                layout = {'canvas': {'positions': {'first': {'x': 50, 'y': 80}, 'second': {'x': 450, 'y': 120}},
                                     'viewport': {'x': 10, 'y': 20, 'zoom': .8}}}
                saved = self.request(client, 'PUT', base + '/workspace', json={'workflow': workflow, 'ui_state': layout})
                output_url, output = self.run_value(client, base, workflow, 'initial')
                self.assertEqual(output['value'], {'value': 18, 'note': 'second'})
                self.request(client, 'PUT', '/api/v2/modules', json={'enabled_package_ids': []})
            for uninstall in (True, False):
                with TestClient(create_application(load_example_results=False)) as client:
                    workspace = self.request(client, 'GET', base + '/workspace')
                    self.assertEqual(workspace['draft']['workflow'], saved['draft']['workflow'])
                    self.assertEqual(workspace['ui_state'], layout)
                    self.assertEqual(self.request(client, 'GET', output_url), output)
                    rejected = client.post(base + '/workflow:commit', json={'workflow': workflow})
                    self.assertEqual(rejected.status_code, 422, rejected.text)
                    self.assertIn('Unknown node_type', rejected.text)
                    if uninstall:
                        inventory = self.request(client, 'GET', '/api/v2/modules')['modules']
                        self.assertEqual([(item['package_id'], item['enabled']) for item in inventory], [('lifecycle_meter', False)])
                        self.request(client, 'DELETE', '/api/v2/modules/lifecycle_meter')
                    else:
                        self.assertEqual(self.request(client, 'GET', '/api/v2/modules')['modules'], [])
                        self.request(client, 'POST', '/api/v2/modules/install', json=install)
                        _, restored = self.run_value(client, base, workflow, 'restored')
                        self.assertEqual(restored['value'], output['value'])
                        self.request(client, 'DELETE', '/api/v2/modules/lifecycle_meter')


if __name__ == '__main__':
    unittest.main()
