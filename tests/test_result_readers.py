"""Public HTTP behavior for persisted module-owned readings; newly written tests."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from protein_workbench_public.bootstrap import create_application


class ResultReaders(unittest.TestCase):
    def test_external_value_can_be_read_after_application_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'modules.json').write_text(json.dumps({'packages': [{
                'package_id': 'reader_demo', 'package_module': 'reader_module',
                'enabled': True, 'source_root': str(Path(__file__).parent.resolve()),
            }]}))
            with patch.dict(os.environ, {'PROTEIN_WORKBENCH_DATA_ROOT': directory}):
                with TestClient(create_application(v2_environment_configuration={})) as client:
                    project = client.post('/api/v2/projects', json={'name': 'Observations'})
                    self.assertEqual(project.status_code, 201, project.text)
                    project_id = project.json()['id']
                    base = f'/api/v2/projects/{project_id}'
                    commit = client.post(base + '/workflow:commit', json={'workflow': {
                        'schema_version': '2.1.0', 'workflow_id': project_id,
                        'nodes': [{'node_id': 'observe', 'node_type_id': 'reader_demo.observe',
                                   'binding_id': 'reader_demo.observe.direct',
                                   'node_parameters': {}, 'binding_parameters': {}}],
                        'edges': [],
                    }})
                    self.assertEqual(commit.status_code, 200, commit.text)
                    receipt = client.post(base + '/runs', json={
                        'workflow_commit_id': commit.json()['workflow_commit_id'],
                        'client_request_id': 'temperature-run',
                    })
                    self.assertEqual(receipt.status_code, 202, receipt.text)
                    run = base + '/runs/' + receipt.json()['run_id']
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        projection = client.get(run).json()
                        if projection['status'] not in ('running', 'admitted'):
                            break
                        time.sleep(.01)
                    self.assertEqual(projection['status'], 'succeeded', projection)
                    raw = client.get(run + '/outputs/observe/observation/values/0')
                    self.assertEqual(raw.status_code, 200, raw.text)
                with TestClient(create_application(v2_environment_configuration={})) as client:
                    reading = client.post(run + '/results:value', json={
                        'node_id': 'observe', 'output_port': 'observation', 'value_index': 0,
                    })
                    self.assertEqual(reading.status_code, 200, reading.text)
                    self.assertEqual(reading.json(), {'kind': 'temperature', 'value': {'temperature': 23.5}})
                    self.assertEqual(client.get(run + '/outputs/observe/observation/values/0').content, raw.content)
                    manifest = client.get('/api/v2/module-ui').json()
                    self.assertIn({'port_type_id': 'reader_demo.temperature', 'kind': 'temperature'}, manifest['readers'])
                    self.assertEqual([v['viewer_id'] for v in manifest['extensions'][0]['viewers'] if v['is_default']], ['reader_demo.celsius'])


if __name__ == '__main__':
    unittest.main()
